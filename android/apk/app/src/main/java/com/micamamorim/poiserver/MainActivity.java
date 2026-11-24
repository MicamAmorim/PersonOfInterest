package com.micamamorim.poiserver;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

public final class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private SharedPreferences preferences;
    private TextView status;
    private EditText hostname;
    private Button authorize;
    private Button openVpn;
    private String authorizeUrl = "";
    private String vpnUrl = "";

    @Override public void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        preferences = ServerService.preferences(this);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(20 * getResources().getDisplayMetrics().density);
        page.setPadding(padding, padding, padding, padding);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(page);
        setContentView(scroll);

        TextView title = new TextView(this);
        title.setText("POI Server");
        title.setTextSize(26);
        page.addView(title);
        status = new TextView(this);
        status.setTextSize(16);
        status.setPadding(0, padding, 0, padding);
        page.addView(status);

        button(page, "Iniciar servidor", () -> {
            if (Build.VERSION.SDK_INT >= 33 &&
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            }
            ServerService.start(this);
        });
        button(page, "Parar servidor", () -> ServerService.stop(this));
        button(page, "Abrir POI neste aparelho", () -> browse(ServerService.LOCAL_URL));

        TextView vpnLabel = new TextView(this);
        vpnLabel.setText("Acesso via Tailscale");
        vpnLabel.setTextSize(18);
        vpnLabel.setPadding(0, padding, 0, 0);
        page.addView(vpnLabel);
        hostname = new EditText(this);
        hostname.setSingleLine(true);
        hostname.setHint("Nome na VPN, ex.: poi-redmi-apk");
        hostname.setText(preferences.getString("hostname", ""));
        page.addView(hostname);
        button(page, "Salvar nome na VPN", () -> {
            String name = hostname.getText().toString().trim().toLowerCase(java.util.Locale.ROOT);
            if (!name.isEmpty() && !name.matches("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")) {
                Toast.makeText(this, "Use letras, números e hífens no nome.", Toast.LENGTH_LONG).show();
                return;
            }
            preferences.edit().putString("hostname", name).apply();
            Toast.makeText(this, name.isEmpty() ? "Acesso pela VPN desativado." :
                "Nome salvo. Inicie o servidor para conectar.", Toast.LENGTH_SHORT).show();
        });
        authorize = button(page, "Autorizar no Tailscale", () -> browse(authorizeUrl));
        openVpn = button(page, "Abrir endereço HTTPS", () -> browse(vpnUrl));
    }

    private Button button(LinearLayout page, String text, Runnable action) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setOnClickListener(view -> action.run());
        page.addView(button);
        return button;
    }

    private void browse(String address) {
        if (address.isEmpty()) return;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(address)));
        } catch (ActivityNotFoundException exception) {
            Toast.makeText(this, "Instale um navegador para abrir o site.", Toast.LENGTH_LONG).show();
        }
    }

    private final Runnable update = new Runnable() {
        @Override public void run() {
            boolean enabled = preferences.getBoolean("enabled", false);
            status.setText(enabled ? preferences.getString("status", "Iniciando servidor…") + "\nInicia ao ligar o aparelho."
                : "Servidor parado.");
            authorizeUrl = "";
            vpnUrl = "";
            String name = preferences.getString("hostname", "");
            if (enabled && !name.isEmpty()) {
                File state = new File(ServerService.vpnState(MainActivity.this, name), "status.json");
                try {
                    JSONObject data = new JSONObject(new String(Files.readAllBytes(state.toPath()), StandardCharsets.UTF_8));
                    String login = data.optString("login");
                    String https = data.optString("https");
                    if (login.startsWith("https://login.tailscale.com/")) authorizeUrl = login;
                    if (https.startsWith("https://") && https.endsWith(".ts.net")) vpnUrl = https;
                } catch (Exception ignored) {
                    // The VPN writes this file after connecting or when it needs authorization.
                }
            }
            authorize.setEnabled(!authorizeUrl.isEmpty());
            openVpn.setEnabled(!vpnUrl.isEmpty());
            if (!vpnUrl.isEmpty()) status.append("\n" + vpnUrl);
            handler.postDelayed(this, 1500);
        }
    };

    @Override protected void onResume() {
        super.onResume();
        handler.post(update);
    }

    @Override protected void onPause() {
        handler.removeCallbacks(update);
        super.onPause();
    }
}
