"""Exercise the real Android overlay input/lifecycle with host Java UI stubs.

Only JNI declarations are replaced in the isolated build; production touch
hit-testing, event handling, border drawing, and lifecycle execute unchanged.
"""
from pathlib import Path
import shutil
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA_ROOT = ROOT / "android/app/src/main/java"
PACKAGE = "com/pokeemerald/experimental/"

STUBS = {
    "android/content/Context.java": """
package android.content;
public class Context {
    public static final String DISPLAY_SERVICE = "display";
    public android.content.res.AssetManager getAssets() { return new android.content.res.AssetManager(); }
    public android.content.res.Resources getResources() { return new android.content.res.Resources(); }
    public Object getSystemService(String name) { return new android.hardware.display.DisplayManager(); }
}
""",
    "android/content/res/AssetManager.java": """
package android.content.res;
public class AssetManager {
    public java.io.InputStream open(String path) throws java.io.IOException { throw new java.io.IOException(); }
}
""",
    "android/content/res/Resources.java": """
package android.content.res;
public class Resources {
    public android.util.DisplayMetrics getDisplayMetrics() { return new android.util.DisplayMetrics(); }
}
""",
    "android/util/DisplayMetrics.java": """
package android.util;
public class DisplayMetrics { public float density = 1; }
""",
    "android/graphics/Rect.java": """
package android.graphics;
public class Rect { public Rect(int l, int t, int r, int b) {} }
""",
    "android/graphics/RectF.java": """
package android.graphics;
public class RectF {
    private float l, t, r, b;
    public RectF() {}
    public RectF(float l, float t, float r, float b) { this.l=l; this.t=t; this.r=r; this.b=b; }
    public boolean contains(float x, float y) { return x >= l && x < r && y >= t && y < b; }
    public float width() { return r-l; }
    public float height() { return b-t; }
    public float centerX() { return (l+r)/2; }
    public float centerY() { return (t+b)/2; }
}
""",
    "android/graphics/Paint.java": """
package android.graphics;
public class Paint {
    public static final int ANTI_ALIAS_FLAG=1, FILTER_BITMAP_FLAG=2;
    public enum Style { STROKE }
    public enum Align { CENTER }
    public static class FontMetrics { public float ascent=-1, descent=1; }
    public Paint(int flags) {}
    public void setColor(int c) {}
    public void setStyle(Style s) {}
    public void setStrokeWidth(float w) {}
    public void setTextAlign(Align a) {}
    public void setFakeBoldText(boolean b) {}
    public void setTextSize(float s) {}
    public FontMetrics getFontMetrics() { return new FontMetrics(); }
}
""",
    "android/graphics/Color.java": """
package android.graphics;
public class Color {
    public static final int TRANSPARENT=0, BLACK=1, WHITE=2;
    public static int argb(int a, int r, int g, int b) { return 0; }
}
""",
    "android/graphics/Bitmap.java": """
package android.graphics;
public class Bitmap {}
""",
    "android/graphics/BitmapFactory.java": """
package android.graphics;
public class BitmapFactory {
    public static Bitmap decodeStream(java.io.InputStream stream) { return new Bitmap(); }
}
""",
    "android/graphics/Canvas.java": """
package android.graphics;
public class Canvas {
    public int rectDraws, bitmapDraws, clipCalls;
    public void drawRect(Rect r, Paint p) { rectDraws++; }
    public void drawRect(RectF r, Paint p) {}
    public void drawRoundRect(RectF r, float x, float y, Paint p) {}
    public void drawText(String s, float x, float y, Paint p) {}
    public void drawBitmap(Bitmap b, Rect source, Rect target, Paint p) { bitmapDraws++; }
    public int save() { return 0; }
    public void clipRect(Rect r) { clipCalls++; }
    public void restoreToCount(int n) {}
}
""",
    "android/view/MotionEvent.java": """
package android.view;
public class MotionEvent {
    public static final int ACTION_DOWN=0, ACTION_UP=1, ACTION_MOVE=2, ACTION_CANCEL=3,
        ACTION_POINTER_DOWN=5, ACTION_POINTER_UP=6;
    private int action, index;
    private float[][] points;
    public MotionEvent(int action, int index, float[]... points) { this.action=action; this.index=index; this.points=points; }
    public int getActionMasked() { return action; }
    public int getActionIndex() { return index; }
    public int getPointerCount() { return points.length; }
    public float getX(int i) { return points[i][0]; }
    public float getY(int i) { return points[i][1]; }
}
""",
    "android/view/View.java": """
package android.view;
public class View {
    public static final int SYSTEM_UI_FLAG_IMMERSIVE_STICKY=1, SYSTEM_UI_FLAG_FULLSCREEN=2,
        SYSTEM_UI_FLAG_HIDE_NAVIGATION=4, SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN=8,
        SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION=16, SYSTEM_UI_FLAG_LAYOUT_STABLE=32;
    private android.content.Context context;
    private int width=1000, height=500;
    public View(android.content.Context context) { this.context=context; }
    public int getWidth() { return width; }
    public int getHeight() { return height; }
    public android.content.res.Resources getResources() { return context.getResources(); }
    public void setBackgroundColor(int c) {}
    public void setSystemUiVisibility(int flags) {}
    public void invalidate() {}
    public void postInvalidate() {}
    public void postInvalidateDelayed(long delay) {}
    public void post(Runnable r) { r.run(); }
    public boolean onTouchEvent(MotionEvent event) { return false; }
    protected void onDraw(android.graphics.Canvas c) {}
    protected void onSizeChanged(int w, int h, int oldW, int oldH) { width=w; height=h; }
    protected void onDetachedFromWindow() {}
    public void setSystemGestureExclusionRects(java.util.List<android.graphics.Rect> rects) {}
}
""",
    "android/view/ViewGroup.java": """
package android.view;
public class ViewGroup extends View {
    public ViewGroup(android.content.Context context) { super(context); }
    public static class LayoutParams {
        public static final int MATCH_PARENT=-1;
        public LayoutParams(int w, int h) {}
    }
    public void addView(View v, LayoutParams p) {}
}
""",
    "android/view/Display.java": """
package android.view;
public class Display {}
""",
    "android/view/Window.java": """
package android.view;
public class Window {
    public void setDecorFitsSystemWindows(boolean fits) {}
    public WindowInsetsController getInsetsController() { return new WindowInsetsController(); }
    public View getDecorView() { return new View(new android.content.Context()); }
    public void addFlags(int flags) {}
}
""",
    "android/view/WindowInsets.java": """
package android.view;
public class WindowInsets { public static class Type { public static int systemBars() { return 0; } } }
""",
    "android/view/WindowInsetsController.java": """
package android.view;
public class WindowInsetsController {
    public static final int BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE=1;
    public void hide(int type) {}
    public void setSystemBarsBehavior(int behavior) {}
}
""",
    "android/view/WindowManager.java": """
package android.view;
public class WindowManager {
    public static class LayoutParams { public static final int FLAG_KEEP_SCREEN_ON=1; }
    public static class InvalidDisplayException extends RuntimeException {}
}
""",
    "android/hardware/display/DisplayManager.java": """
package android.hardware.display;
public class DisplayManager {
    public static final String DISPLAY_CATEGORY_PRESENTATION="presentation";
    public android.view.Display[] getDisplays(String category) { return new android.view.Display[0]; }
}
""",
    "android/os/Bundle.java": """
package android.os;
public class Bundle {}
""",
    "android/os/Build.java": """
package android.os;
public class Build {
    public static class VERSION { public static final int SDK_INT=35; }
    public static class VERSION_CODES { public static final int Q=29, R=30; }
}
""",
    "android/os/SystemClock.java": """
package android.os;
public class SystemClock { public static long uptimeMillis() { return 0; } }
""",
    "android/os/Looper.java": """
package android.os;
public class Looper { public static Looper getMainLooper() { return new Looper(); } }
""",
    "android/os/Handler.java": """
package android.os;
public class Handler {
    public Handler(Looper looper) {}
    public void postDelayed(Runnable r, long delay) {}
    public void removeCallbacks(Runnable r) {}
}
""",
    "org/libsdl/app/SDLActivity.java": """
package org.libsdl.app;
public class SDLActivity extends android.content.Context {
    protected android.view.ViewGroup mLayout=new android.view.ViewGroup(this);
    protected android.view.View mSurface=new android.view.View(this);
    protected void onCreate(android.os.Bundle bundle) {}
    protected void onResume() {}
    protected void onPause() {}
    protected String[] getLibraries() { return new String[0]; }
    public void onWindowFocusChanged(boolean focus) {}
    public void setOrientationBis(int w, int h, boolean resizable, String hint) {}
    public android.view.Window getWindow() { return new android.view.Window(); }
}
""",
    PACKAGE + "DualScreenPresentation.java": """
package com.pokeemerald.experimental;
public class DualScreenPresentation {
    public DualScreenPresentation(android.content.Context c, android.view.Display d) {}
    public boolean isShowing() { return false; }
    public void updateState(DualScreenState state) {}
    public void navigate(int action) {}
    public void setSettingsListener(Runnable listener) {}
    public android.view.Window getWindow() { return new android.view.Window(); }
    public void show() {}
    public void dismiss() {}
}
""",
    PACKAGE + "DualScreenState.java": """
package com.pokeemerald.experimental;
public class DualScreenState { public static DualScreenState parse(String s) { return new DualScreenState(); } }
""",
    PACKAGE + "DualScreenBridge.java": """
package com.pokeemerald.experimental;
public class DualScreenBridge {
    public static final int SETTING_TOUCH_CONTROLS=8, SETTING_WIDESCREEN=7, SETTING_BACKGROUND_MODE=6;
    public static int[] settings=new int[14];
    public static int held;
    public static boolean voxelActive;
    public static void nativeSetPlatformSetting(int setting, int value) { settings[setting]=value; }
    public static String nativeGetSnapshotJson() { return "{}"; }
    public static int nativeDrainNavKey() { return -1; }
}
""",
}

HARNESS = """
package com.pokeemerald.experimental;
import android.view.MotionEvent;
public class GbaControlsHarness {
    private static final float[] UP={93,295}, LEFT={52,350}, DIAGONAL={52,295},
        A={937,320}, B={922,410}, EMPTY={500,250}, TOGGLE={500,25};
    private static void mask(int expected) {
        if (DualScreenBridge.held != expected) throw new AssertionError("held="+DualScreenBridge.held+", expected="+expected);
    }
    private static void press(GbaControlsView view, float[] point) {
        if (!view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN,0,point))) throw new AssertionError("button ignored");
    }
    public static void main(String[] args) throws Exception {
        DualScreenBridge.settings[8]=1;
        GbaControlsView view=new GbaControlsView(new android.content.Context());
        press(view,UP); mask(64);
        // A second finger presses A while the original keeps movement held.
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_POINTER_DOWN,1,UP,A)); mask(65);
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_MOVE,0,LEFT,A)); mask(33);
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_POINTER_UP,1,LEFT,A)); mask(32);
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP,0,LEFT)); mask(0);
        press(view,DIAGONAL); mask(96);
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_POINTER_DOWN,1,DIAGONAL,B)); mask(98);
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_CANCEL,0,DIAGONAL,B)); mask(0);
        if (view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN,0,EMPTY))) throw new AssertionError("game touch consumed");
        press(view,A); mask(1);
        view.onSizeChanged(1000,500,1000,500); mask(0);
        press(view,A); view.onDetachedFromWindow(); mask(0);
        press(view,A); DualScreenBridge.settings[8]=0;
        view.onDraw(new android.graphics.Canvas()); mask(0);
        // An existing config with buttons hidden can enable them on one display.
        press(view,TOGGLE);
        // Snapshot-driven redraws must not cancel the toggle while hidden.
        view.onDraw(new android.graphics.Canvas());
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP,0,TOGGLE));
        if (DualScreenBridge.settings[8]!=1) throw new AssertionError("show toggle not persisted");
        press(view,A); mask(1);
        press(view,TOGGLE); mask(0);
        view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP,0,TOGGLE));
        if (DualScreenBridge.settings[8]!=0) throw new AssertionError("hide toggle failed");
        if (view.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN,0,A))) throw new AssertionError("hidden button accepted");
        DualScreenBridge.settings[8]=1;
        PokeEmeraldActivity activity=new PokeEmeraldActivity();
        activity.onCreate(null);
        java.lang.reflect.Field field=PokeEmeraldActivity.class.getDeclaredField("controls");
        field.setAccessible(true);
        GbaControlsView controls=(GbaControlsView)field.get(activity);
        press(controls,A); activity.onPause(); mask(0);
        press(controls,A); activity.onWindowFocusChanged(false); mask(0);
        System.out.println("multitouch, diagonals, releases, outside passthrough, and persisted toggle passed");
    }
}
"""


BORDER_HARNESS = """
package com.pokeemerald.experimental;
import android.graphics.Canvas;
import android.graphics.Bitmap;
public class GbaBorderHarness {
    private static Canvas draw(GbaControlsView view) {
        Canvas canvas=new Canvas(); view.onDraw(canvas); return canvas;
    }
    private static void counts(Canvas canvas, int rects, int bitmaps, int clips) {
        if (canvas.rectDraws!=rects || canvas.bitmapDraws!=bitmaps || canvas.clipCalls!=clips)
            throw new AssertionError("rects="+canvas.rectDraws+", bitmaps="+canvas.bitmapDraws+", clips="+canvas.clipCalls);
    }
    public static void main(String[] args) throws Exception {
        DualScreenBridge.settings[8]=0; // no touch buttons in the mask count
        DualScreenBridge.settings[6]=1; // solid black letterbox regions
        DualScreenBridge.settings[7]=0;
        DualScreenBridge.settings[11]=1; // saved preference may differ from actual renderer
        GbaControlsView view=new GbaControlsView(new android.content.Context());
        DualScreenBridge.voxelActive=false;
        counts(draw(view),4,0,0); // classic, including GLES setup failure fallback
        DualScreenBridge.voxelActive=true;
        counts(draw(view),0,0,0); // GLES full-surface UI cannot be covered by classic bars
        DualScreenBridge.voxelActive=false;
        DualScreenBridge.settings[7]=1;
        counts(draw(view),0,0,0); // existing classic widescreen behavior
        DualScreenBridge.settings[7]=0;
        DualScreenBridge.settings[6]=0;
        DualScreenBridge.settings[4]=1;
        java.lang.reflect.Field backgrounds=GbaControlsView.class.getDeclaredField("backgrounds");
        backgrounds.setAccessible(true); ((Bitmap[])backgrounds.get(view))[0]=new Bitmap();
        java.lang.reflect.Field count=GbaControlsView.class.getDeclaredField("backgroundCount");
        count.setAccessible(true); count.setInt(view,1);
        java.lang.reflect.Field border=GbaControlsView.class.getDeclaredField("border");
        border.setAccessible(true); border.set(view,new Bitmap());
        counts(draw(view),0,5,4); // four background clips plus the decorative border
        DualScreenBridge.voxelActive=true;
        counts(draw(view),0,0,0); // neither masks nor decoration hide any GLES UI pixels
        System.out.println("actual voxel state, classic fallback, and widescreen border behavior passed");
    }
}
"""


class TouchControlsTests(unittest.TestCase):
    def test_android_overlay_multitouch_toggle_and_lifecycle(self):
        self._run_java_harness(HARNESS, "GbaControlsHarness")

    def test_overlay_border_matches_actual_renderer(self):
        self._run_java_harness(BORDER_HARNESS, "GbaBorderHarness")

    def _run_java_harness(self, harness, class_name):
        java = shutil.which("java")
        javac = shutil.which("javac")
        if java is None:
            self.skipTest("Java is required to exercise Android touch input")
        compiler = [javac] if javac else [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"]
        probe = subprocess.run(compiler + ["-version"], capture_output=True, text=True)
        if probe.returncode:
            self.skipTest("JDK compiler is required to exercise Android touch input")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = dict(STUBS)
            source = (JAVA_ROOT / PACKAGE / "GbaControlsView.java").read_text()
            replacements = {
                "private static native boolean isVoxelRendererActive();":
                    "private static boolean isVoxelRendererActive() { return DualScreenBridge.voxelActive; }",
                "private static native void setTouchKeys(int mask);":
                    "private static void setTouchKeys(int mask) { DualScreenBridge.held = mask; }",
                "private static native int getBorderBackground();":
                    "private static int getBorderBackground() { return 0; }",
                "private static native int getPlatformSetting(int setting);":
                    "private static int getPlatformSetting(int setting) { return DualScreenBridge.settings[setting]; }",
            }
            for before, after in replacements.items():
                self.assertEqual(source.count(before), 1, "isolated test JNI boundary changed")
                source = source.replace(before, after)
            sources[PACKAGE + "GbaControlsView.java"] = source
            sources[PACKAGE + "PokeEmeraldActivity.java"] = (JAVA_ROOT / PACKAGE / "PokeEmeraldActivity.java").read_text()
            sources[PACKAGE + class_name + ".java"] = harness
            for path, text in sources.items():
                output = root / path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(text)
            result = subprocess.run(compiler + ["-d", str(root / "classes")] +
                                    [str(root / path) for path in sources], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([java, "-cp", str(root / "classes"),
                                     "com.pokeemerald.experimental." + class_name],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_native_touch_mask_preserves_physical_and_queued_input(self):
        compiler = shutil.which("cc") or shutil.which("gcc")
        if compiler is None:
            self.skipTest("C compiler is required to exercise native touch input")
        source = (ROOT / "src/platform/sdl2.c").read_text()

        def function(pattern):
            match = re.search(pattern, source)
            self.assertIsNotNone(match, "native touch integration missing")
            opening = source.index("{", match.start())
            depth = 1
            end = opening + 1
            while depth:
                depth += (source[end] == "{") - (source[end] == "}")
                end += 1
            return source[match.start():end]

        setter = function(r"JNIEXPORT void JNICALL Java_com_pokeemerald_experimental_GbaControlsView_setTouchKeys\(")
        getter = function(r"u16 Platform_GetKeyInput\(void\)")
        fixture = r"""
#include <stdint.h>
#include <assert.h>
typedef uint16_t u16;
typedef uint8_t u8;
typedef int jint;
typedef void JNIEnv;
typedef void *jclass;
#define JNIEXPORT
#define JNICALL
#define PLATFORM_SETTING_TOUCH_CONTROLS 8
typedef struct { int value; } SDL_atomic_t;
static int SDL_AtomicSet(SDL_atomic_t *a, int value) { int old=a->value; a->value=value; return old; }
static int SDL_AtomicGet(SDL_atomic_t *a) { return a->value; }
static SDL_atomic_t sAndroidTouchKeys;
static u8 sPlatformSettings[14];
static u16 keyboardKeys=1, controllerKeys=2, controllerAxisKeys=32;
static u16 queued=8;
static u16 DualScreen_ConsumeVirtualKeys(void) { u16 result=queued; queued=0; return result; }
""" + setter + "\n" + getter + r"""
int main(void) {
    sPlatformSettings[PLATFORM_SETTING_TOUCH_CONTROLS]=1;
    Java_com_pokeemerald_experimental_GbaControlsView_setTouchKeys(0,0,64);
    assert(Platform_GetKeyInput()==(1|2|32|64|8));
    assert(Platform_GetKeyInput()==(1|2|32|64)); // held, not a one-frame queue
    Java_com_pokeemerald_experimental_GbaControlsView_setTouchKeys(0,0,0);
    assert(Platform_GetKeyInput()==(1|2|32)); // physical sources keep their held state
    Java_com_pokeemerald_experimental_GbaControlsView_setTouchKeys(0,0,0xFFFF);
    assert(Platform_GetKeyInput()==0x3FF); // only the ten GBA buttons
    sPlatformSettings[PLATFORM_SETTING_TOUCH_CONTROLS]=0;
    assert(Platform_GetKeyInput()==(1|2|32)); // hidden controls cannot hold game keys
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "touch.c"
            path.write_text(fixture)
            result = subprocess.run([compiler, "-D__ANDROID__", "-std=c11", str(path),
                                     "-o", str(root / "touch")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(root / "touch")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
