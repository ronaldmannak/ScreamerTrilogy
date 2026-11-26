#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE
#endif
#define main unusedPreviewMain
#include PREVIEW_SOURCE_FILE
#undef main
int main(){@autoreleasepool{
    [NSApplication sharedApplication];
    PreviewRenderer *renderer=[PreviewRenderer new];renderer->state=std::make_unique<State>();
    PreviewApp *app=[PreviewApp new];app.renderer=renderer;
    renderer->state->bundledGameUI=true;[app installMenus];
    if([NSApp.mainMenu itemWithTitle:@"Rendering"]||NSApp.mainMenu.numberOfItems!=1)return 1;
    renderer->state->bundledGameUI=false;[app installMenus];
    NSMenuItem *render=[NSApp.mainMenu itemWithTitle:@"Rendering"];
    if(!render||render.submenu.numberOfItems!=3)return 2;
    if(renderer->state->sessionTask||renderer->state->inputPath)return 3;
    puts("Bundled game has no rendering options; standalone diagnostics retain them. No game/input started.");return 0;
}}
