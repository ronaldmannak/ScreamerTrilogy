// Headless checks of the real renderer projection; no NSApplication or windows.
#ifndef PREVIEW_SOURCE_FILE
#error Compile with PREVIEW_SOURCE_FILE pointing to the worktree source.
#endif
#define main NativePreviewApplicationMain
#include PREVIEW_SOURCE_FILE
#undef main
#include <cassert>
#include <cstdio>

static double screenX(float4x4 p,float4 v,double width) {
    auto q=p*v;return (q.x/q.w+1)*width*.5;
}
static double screenY(float4x4 p,float4 v,double height) {
    auto q=p*v;return (1-q.y/q.w)*height*.5;
}
// viewW/viewH here mean physical layer/display frame points, NOT NSView.bounds.
static double presentedPointAspect(double renderAspect,double drawableW,double drawableH,double viewW,double viewH) {
    double drawableAspect=drawableW/drawableH;
    double quadX=std::min(1.0,renderAspect/drawableAspect);
    double quadY=std::min(1.0,drawableAspect/renderAspect);
    return viewW*quadX/(viewH*quadY);
}
static void near(double a,double b,double epsilon=1e-3) {assert(std::isfinite(a)&&std::fabs(a-b)<epsilon);}
int main() {
    checkProjectionMath(); // Existing checks execute the actual source function.
    Projection original;
    auto narrow=replayProjection(original,4.f/3.f,100000);
    auto wide=replayProjection(original,16.f/9.f,100000);
    // Same 720px height: original central 960px picture retains every projected
    // point's size/position, with160px additional scenery on either side.
    for(float x:{-900.f,-100.f,0.f,550.f,1500.f})
      for(float y:{-300.f,0.f,700.f})
        for(float z:{-128.f,-1000.f,-10000.f}) {
            float4 point={x,y,z,1};
            near(screenX(wide,point,1280)-screenX(narrow,point,960),160,.01);
            near(screenY(wide,point,720),screenY(narrow,point,720),.01);
        }
    constexpr double game=16.0/9.0;
    // Matched backing scales preserve16:9 for16:9,16:10, ultrawide and portrait
    // destination views. Black bars absorb the unused destination area.
    for(auto size:{std::pair<double,double>{1280,720},{1280,800},{2560,1080},{900,1440}})
      for(double scale:{1.,2.})
        near(presentedPointAspect(game,size.first*scale,size.second*scale,size.first,size.second),game);
    // Conditional counterexample: IF physical layer frame is659×1440points,
    // backingX2/backingY1 turns16:9 into8:9. Existing telemetry reportsbounds,
    // so the real app needs frame/layer/backing geometry to establish this.
    near(presentedPointAspect(game,1318,1440,659,1440),8.0/9.0);
    // A physically659×371point layer +1318×1440drawable also distorts.
    assert(std::fabs(presentedPointAspect(game,1318,1440,659,371)-game)>.5);
    std::puts("Projection preserves central framing; matched backing preserves16:9; anisotropic physical backing reproduces portrait.");
}
