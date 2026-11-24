package com.micamamorim.poiserver;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.concurrent.TimeUnit;

public final class ServerService extends Service {
    static final String LOCAL_URL = "http://127.0.0.1:18080";
    private static final String RTC_URL = "http://127.0.0.1:11984";
    private static final String CHANNEL = "poi_server";
    private static final int NOTIFICATION = 80;
    private static final String STOP = "poi.stop";

    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile boolean stopping;
    private volatile boolean videoExited;
    private volatile PyObject server;
    private Thread worker;
    private PowerManager.WakeLock wakeLock;
    private Process vpn;
    private String vpnHostname = "";
    private long nextVpnAttempt;

    static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences("poi", Context.MODE_PRIVATE);
    }

    static File vpnState(Context context, String hostname) {
        return new File(context.getFilesDir(), "vpn-" + hostname);
    }

    static void start(Context context) {
        preferences(context).edit().putBoolean("enabled", true).apply();
        context.startForegroundService(new Intent(context, ServerService.class));
    }

    static void stop(Context context) {
        preferences(context).edit().putBoolean("enabled", false).apply();
        context.startService(new Intent(context, ServerService.class).setAction(STOP));
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) {
            stopping = true;
            setStatus("Encerrando o servidor.");
            if (worker == null) stopSelf();
            return START_NOT_STICKY;
        }
        if (!preferences(this).getBoolean("enabled", false)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        startForeground(NOTIFICATION, notification("Servidor POI ativado"));
        stopping = false;
        if (worker == null) {
            PowerManager manager = getSystemService(PowerManager.class);
            wakeLock = manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "POI:server");
            wakeLock.acquire();
            worker = new Thread(this::supervise, "POI server");
            worker.start();
        }
        return START_STICKY;
    }

    private Notification notification(String text) {
        getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel(CHANNEL, "Servidor POI", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("POI Server").setContentText(text).setContentIntent(open).setOngoing(true).build();
    }

    static boolean reachable(String url) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection(java.net.Proxy.NO_PROXY);
            connection.setConnectTimeout(750);
            connection.setReadTimeout(750);
            return connection.getResponseCode() == 200;
        } catch (IOException ignored) {
            return false;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private File executable(String name) {
        return new File(getApplicationInfo().nativeLibraryDir, "libpoi_" + name + ".so");
    }

    private File makeDirectory(String name) throws IOException {
        File directory = new File(getFilesDir(), name);
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Pasta indisponível: " + name);
        return directory;
    }

    private File prepareWeb() throws IOException {
        File directory = makeDirectory("web");
        for (String asset : getAssets().list("poiWeb")) {
            try (InputStream contents = getAssets().open("poiWeb/" + asset)) {
                Files.copy(contents, new File(directory, asset).toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
        }
        if (!new File(directory, "lite.html").isFile()) throw new IOException("Interface do POI ausente");
        return directory;
    }

    private Process launch(File directory, String name, String... args) throws IOException {
        String[] command = new String[args.length + 1];
        command[0] = executable(name).getPath();
        System.arraycopy(args, 0, command, 1, args.length);
        ProcessBuilder builder = new ProcessBuilder(command).directory(directory).redirectErrorStream(true);
        builder.redirectOutput(new File(directory, name + ".log"));
        builder.environment().put("HOME", getFilesDir().getPath());
        builder.environment().put("SSL_CERT_DIR", "/system/etc/security/cacerts");
        return builder.start();
    }

    private static void terminate(Process process) {
        if (process == null) return;
        process.destroy();
        try {
            if (!process.waitFor(3, TimeUnit.SECONDS)) process.destroyForcibly();
        } catch (InterruptedException exception) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
        }
    }

    private void reconcileVpn() throws IOException {
        String name = preferences(this).getString("hostname", "");
        if (!name.equals(vpnHostname)) {
            terminate(vpn);
            vpn = null;
            vpnHostname = name;
            nextVpnAttempt = 0;
        }
        if (name.isEmpty() || (vpn != null && vpn.isAlive()) || SystemClock.elapsedRealtime() < nextVpnAttempt) return;
        nextVpnAttempt = SystemClock.elapsedRealtime() + 5000;
        File state = makeDirectory("vpn-" + name);
        Files.deleteIfExists(new File(state, "status.json").toPath());
        vpn = launch(state, "vpn", "-state", state.getPath(), "-hostname", name, "-backend", LOCAL_URL);
    }

    private void monitor(Process media) {
        try {
            boolean announced = false;
            while (!stopping && media.isAlive() && !Thread.currentThread().isInterrupted()) {
                if (!announced && reachable(LOCAL_URL + "/api/health")) {
                    setStatus("Servidor online.");
                    announced = true;
                }
                try {
                    reconcileVpn();
                } catch (IOException exception) {
                    Log.w("POIServer", "VPN indisponível", exception);
                }
                Thread.sleep(1000);
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        } finally {
            videoExited = !media.isAlive();
            if (stopping || videoExited) {
                PyObject python = server;
                if (python != null) python.callAttr("request_stop");
            }
            terminate(vpn);
            vpn = null;
            vpnHostname = "";
        }
    }

    private void serve(File data, File web) throws Exception {
        Process media = null;
        Thread monitor = null;
        try {
            File config = new File(data, "go2rtc.yaml");
            String yaml = "api:\n  listen: \"127.0.0.1:11984\"\nrtsp:\n  listen: \"127.0.0.1:18554\"\nwebrtc:\n  listen: \"\"\nstreams: {}\n";
            Files.write(config.toPath(), yaml.getBytes(StandardCharsets.UTF_8));
            media = launch(data, "go2rtc", "-c", config.getPath());
            boolean ready = false;
            for (int i = 0; i < 30 && !stopping && media.isAlive(); i++) {
                if (reachable(RTC_URL + "/api/streams")) {
                    ready = true;
                    break;
                }
                Thread.sleep(150);
            }
            if (stopping) return;
            if (!ready) throw new IOException("O serviço de vídeo não iniciou.");
            videoExited = false;
            Process monitored = media;
            monitor = new Thread(() -> monitor(monitored), "POI video and VPN");
            monitor.start();
            boolean started = server.callAttr("run", data.getPath(), web.getPath(), executable("ffmpeg").getPath()).toBoolean();
            if (!stopping && (!started || videoExited)) throw new IOException("Servidor interrompido. Tentando novamente.");
        } finally {
            if (monitor != null) {
                monitor.interrupt();
                monitor.join(5000);
            }
            terminate(media);
        }
    }

    private void supervise() {
        try {
            File data = makeDirectory("data");
            File web = prepareWeb();
            if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
            server = Python.getInstance().getModule("poi_android");
            while (!stopping) {
                setStatus("Iniciando servidor…");
                try {
                    serve(data, web);
                } catch (Exception exception) {
                    Log.e("POIServer", "Falha no servidor", exception);
                    setStatus("Servidor interrompido. Tentando novamente.");
                }
                if (!stopping) Thread.sleep(4000);
            }
        } catch (Exception exception) {
            Log.e("POIServer", "Falha ao preparar o aplicativo", exception);
            setStatus("Falha ao preparar o aplicativo.");
        } finally {
            server = null;
            main.post(() -> {
                worker = null;
                stopSelf();
            });
        }
    }

    private void setStatus(String status) {
        preferences(this).edit().putString("status", status).apply();
    }

    @Override public void onDestroy() {
        stopping = true;
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }
}
