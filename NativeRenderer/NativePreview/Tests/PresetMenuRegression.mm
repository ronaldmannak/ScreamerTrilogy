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
    if([NSApp.mainMenu itemWithTitle:@"Rendering"]||NSApp.mainMenu.numberOfItems!=2)return 1;
    NSMenuItem *conditions=[NSApp.mainMenu itemWithTitle:@"Conditions"];
    if(!conditions||conditions.submenu.numberOfItems!=3)return 2;
    NSArray<NSString *> *titles=@[@"Day",@"Night",@"Fog"];
    auto &state=*renderer->state;BOOL wide=state.widescreen,extended=state.extendedDistance,high=state.render4K;
    for(NSInteger index=0;index<3;index++){
        NSMenuItem *item=[conditions.submenu itemAtIndex:index];
        if(![item.title isEqual:titles[index]]||item.tag!=index||![item.keyEquivalent isEqual:[NSString stringWithFormat:@"%ld",(long)index+1]]||item.keyEquivalentModifierMask!=NSEventModifierFlagCommand||item.target!=app)return 3;
        if(item.state!=(index==0?NSControlStateValueOn:NSControlStateValueOff))return 4;
    }
    for(NSNumber *selection in @[@1,@2,@0]){
        NSInteger chosen=selection.integerValue;
        NSMenuItem *item=[conditions.submenu itemAtIndex:chosen];[app changeConditions:item];
        if(static_cast<NSInteger>(state.conditionsTransition.target)!=chosen)return 5;
        for(NSInteger index=0;index<3;index++)if([conditions.submenu itemAtIndex:index].state!=(index==chosen?NSControlStateValueOn:NSControlStateValueOff))return 6;
        if(state.widescreen!=wide||state.extendedDistance!=extended||state.render4K!=high||state.inputSeq||state.sessionTask||state.inputPath)return 7;
    }
    NSMenuItem *invalid=[NSMenuItem new];invalid.tag=9;[app changeConditions:invalid];
    if(state.conditionsTransition.target!=Conditions::Preset::Day)return 8;
    renderer->state->bundledGameUI=false;[app installMenus];
    NSMenuItem *render=[NSApp.mainMenu itemWithTitle:@"Rendering"];
    if(!render||render.submenu.numberOfItems!=3||![NSApp.mainMenu itemWithTitle:@"Conditions"])return 9;
    if(renderer->state->sessionTask||renderer->state->inputPath)return 10;
    state.livePath=@"/tmp/conditions-test/live.json";state.nightKnown=true;state.nightAvailable=false;
    NSMenuItem *night=[[NSApp.mainMenu itemWithTitle:@"Conditions"].submenu itemAtIndex:1];
    if([app validateMenuItem:night])return 11;
    [app changeConditions:night];if(state.conditionsTransition.target!=Conditions::Preset::Day)return 12;
    state.nightAvailable=true;if(![app validateMenuItem:night])return 13;
    state.originalNight=true;NSMenuItem *original=[[NSApp.mainMenu itemWithTitle:@"Conditions"].submenu itemAtIndex:0];
    [app validateMenuItem:original];if(![original.title isEqual:@"Original (Night)"])return 14;
    NSMenuItem *fog=[[NSApp.mainMenu itemWithTitle:@"Conditions"].submenu itemAtIndex:2];
    state.fogKnown=true;state.fogAvailable=false;
    if([app validateMenuItem:fog])return 15;
    [app changeConditions:fog];if(state.conditionsTransition.target!=Conditions::Preset::Day)return 16;
    state.fogAvailable=true;if(![app validateMenuItem:fog])return 17;
    state.originalFog=true;[app validateMenuItem:original];if(![original.title isEqual:@"Original (Fog)"])return 18;
    puts("Conditions menu and Cmd1/2/3 switch live presets without game input or physics changes; rendering controls remain diagnostic-only.");return 0;
}}
