package com.micamamorim.poiserver;
import android.content.*;
public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction()) &&
            c.getSharedPreferences("poi",Context.MODE_PRIVATE).getBoolean("enabled",false))
            ServerService.start(c);
    }
}
