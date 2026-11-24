package com.micamamorim.poiserver;

import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import java.net.*;
import java.util.concurrent.*;

public final class ServerService extends Service {
    static final String ACTION_START = "com.micamamorim.poiserver.START";
    static final String ACTION_STOP = "com.micamamorim.poiserver.STOP";
    private static final String CHANNEL = "poi_status";
    private ScheduledExecutorService executor;
    private long lastAttempt;
    private String lastStatus = "";

    static void start(Context c) {
        Intent i = new Intent(c,ServerService.class).setAction(ACTION_START);
        if (Build.VERSION.SDK_INT>=26) c.startForegroundService(i); else c.startService(i);
    }
    static void stop(Context c) {
        c.startService(new Intent(c,ServerService.class).setAction(ACTION_STOP));
    }
    @Override public void onCreate() {
        super.onCreate();
        NotificationChannel channel = new NotificationChannel(CHANNEL,"Servidor POI",NotificationManager.IMPORTANCE_LOW);
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
        startForeground(1408,notification("Iniciando monitoramento"));
        executor=Executors.newSingleThreadScheduledExecutor();
        executor.scheduleWithFixedDelay(this::check,1,25,TimeUnit.SECONDS);
    }
    private Notification notification(String msg) {
        PendingIntent pi=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),
            PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("PersonOfInterest Server").setContentText(msg)
            .setContentIntent(pi).setOngoing(true).build();
    }
    private void status(String s) {
        if (lastStatus.equals(s)) return;
        lastStatus=s;
        getSharedPreferences("poi",MODE_PRIVATE).edit().putString("status",s).apply();
        getSystemService(NotificationManager.class).notify(1408,notification(s));
    }
    static boolean healthy() {
        HttpURLConnection c=null;
        try {
            c=(HttpURLConnection)new URL("http://127.0.0.1:8080/api/health").openConnection();
            c.setConnectTimeout(1500);c.setReadTimeout(1500);c.setUseCaches(false);
            return c.getResponseCode()==200;
        } catch(Exception e){ return false; }
        finally { if(c!=null)c.disconnect(); }
    }
    private void check() {
        if (healthy()) { status("Servidor online na porta 8080"); return; }
        if(checkSelfPermission("com.termux.permission.RUN_COMMAND")!=PackageManager.PERMISSION_GRANTED) {
            status("Conceda permissão: executar comandos no Termux");return;
        }
        try { getPackageManager().getPackageInfo("com.termux",0); }
        catch(PackageManager.NameNotFoundException e){status("Instale Termux");return;}
        long now=SystemClock.elapsedRealtime();
        if(lastAttempt!=0 && now-lastAttempt<120000){status("Aguardando servidor");return;}
        lastAttempt=now;
        try { launch();status("Comando de inicialização enviado"); }
        catch(Exception e){status("Falha: "+e.getClass().getSimpleName());}
    }
    private void launch() {
        String host=getSharedPreferences("poi",MODE_PRIVATE).getString("hostname","").trim();
        if(!host.isEmpty() && !host.matches("[A-Za-z0-9][A-Za-z0-9-]{0,62}"))
            throw new IllegalArgumentException("Hostname inválido");
        String assignment=host.isEmpty()?"":"POI_TAILSCALE_HOSTNAME="+host+" ";
        String inner="cd \"$HOME/PersonOfInterest\" && "+assignment+"exec bash android/run.sh";
        String command="termux-wake-lock >/dev/null 2>&1 || true; "+
            "exec proot-distro login --shared-tmp --kernel \"$(uname -r)\" poi-debian "+
            "-- /bin/bash -lc '"+inner+"'";
        Intent intent=new Intent("com.termux.RUN_COMMAND");
        intent.setClassName("com.termux","com.termux.app.RunCommandService");
        intent.putExtra("com.termux.RUN_COMMAND_PATH","/data/data/com.termux/files/usr/bin/bash");
        intent.putExtra("com.termux.RUN_COMMAND_ARGUMENTS",new String[]{"-lc",command});
        intent.putExtra("com.termux.RUN_COMMAND_WORKDIR","/data/data/com.termux/files/home");
        intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND",true);
        startService(intent);
    }
    @Override public int onStartCommand(Intent i,int flags,int id){
        if(i!=null && ACTION_STOP.equals(i.getAction())){
            getSharedPreferences("poi",MODE_PRIVATE).edit().putBoolean("enabled",false).apply();
            stopForeground(true);stopSelf();return START_NOT_STICKY;
        }
        getSharedPreferences("poi",MODE_PRIVATE).edit().putBoolean("enabled",true).apply();
        return START_STICKY;
    }
    @Override public void onDestroy(){if(executor!=null)executor.shutdownNow();super.onDestroy();}
    @Override public IBinder onBind(Intent i){return null;}
}
