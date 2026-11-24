package com.micamamorim.poiserver;

import android.Manifest;
import android.app.Activity;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.graphics.Color;
import android.widget.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private TextView status;
    private EditText hostname;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    @Override public void onCreate(Bundle b){
        super.onCreate(b);
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(1);layout.setPadding(30,30,30,30);
        layout.setBackgroundColor(Color.rgb(246,247,251));
        ScrollView sc=new ScrollView(this);sc.addView(layout);setContentView(sc);
        TextView title=new TextView(this);title.setText("POI Server — Android");title.setTextSize(23);
        title.setPadding(0,0,0,12);layout.addView(title);
        TextView note=new TextView(this);
        note.setText("Beta: controlador do servidor existente no Termux/Debian, ainda não é APK independente.");
        layout.addView(note);
        status=new TextView(this);status.setTextSize(17);status.setPadding(0,20,0,18);layout.addView(status);
        hostname=new EditText(this);hostname.setSingleLine(true);hostname.setHint("Hostname Tailscale (opcional)");
        hostname.setText(getSharedPreferences("poi",MODE_PRIVATE).getString("hostname",""));layout.addView(hostname);
        button(layout,"Salvar hostname",()->{
            String host=hostname.getText().toString().trim();
            if(!host.isEmpty()&&!host.matches("[A-Za-z0-9][A-Za-z0-9-]{0,62}")){
                Toast.makeText(this,"Hostname inválido",Toast.LENGTH_LONG).show();return;
            }
            getSharedPreferences("poi",MODE_PRIVATE).edit().putString("hostname",host).apply();
            Toast.makeText(this,"Salvo. Reinicie o servidor para aplicar.",Toast.LENGTH_LONG).show();
        });
        button(layout,"Iniciar e manter ativo",()->{
            if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},32);
            ServerService.start(this);
        });
        button(layout,"Parar monitoramento",()->ServerService.stop(this));
        button(layout,"Abrir painel local",()->startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse("http://127.0.0.1:8080"))));
        button(layout,"Autorizar comandos no Termux",()->requestPermissions(new String[]{"com.termux.permission.RUN_COMMAND"},33));
        button(layout,"Configurar economia de bateria",()->startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)));
        TextView guide=new TextView(this);
        guide.setText("\nConfiguração inicial:\n1. Mantenha a instalação Android Lite já funcional no Termux.\n2. Ative allow-external-apps=true em ~/.termux/termux.properties e execute termux-reload-settings.\n3. Conceda a permissão do Termux acima.\n4. Habilite autostart e bateria sem restrições para ambos os aplicativos no MIUI.\n5. Toque Iniciar. O monitor continuará com a tela apagada e tentará reiniciar após o boot.\n\nO botão Parar interrompe apenas o monitoramento, não a gravação em andamento no Termux.");
        layout.addView(guide);
    }
    private void button(LinearLayout l,String s,Runnable r){
        Button b=new Button(this);b.setText(s);b.setAllCaps(false);b.setOnClickListener(v->r.run());l.addView(b);
    }
    private final Runnable refresh=new Runnable(){
        @Override public void run(){
            io.execute(()->{
                boolean online=ServerService.healthy();
                boolean enabled=getSharedPreferences("poi",MODE_PRIVATE).getBoolean("enabled",false);
                String detail=getSharedPreferences("poi",MODE_PRIVATE).getString("status","");
                runOnUiThread(()->status.setText((online?"Servidor online":"Servidor offline")+
                    "\nMonitoramento: "+(enabled?"ativado":"desativado")+"\n"+detail));
            });
            ui.postDelayed(this,6000);
        }
    };
    @Override protected void onResume(){super.onResume();ui.removeCallbacks(refresh);ui.post(refresh);}
    @Override protected void onPause(){ui.removeCallbacks(refresh);super.onPause();}
    @Override protected void onDestroy(){io.shutdownNow();super.onDestroy();}
}
