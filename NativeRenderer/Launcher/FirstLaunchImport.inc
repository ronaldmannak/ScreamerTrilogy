// Source-only first-launch setup. Imported files never enter the signed bundle.
static NSTask *importTask(NSString *resources, NSDictionary *profile, NSString *content,
                          NSString *source, NSString *glide, BOOL validate) {
    NSTask *task=[NSTask new];
    task.executableURL=[NSURL fileURLWithPath:[resources stringByAppendingPathComponent:@"Python/bin/python3.14"]];
    NSMutableArray *args=[NSMutableArray arrayWithArray:@[@"-B",[resources stringByAppendingPathComponent:@"Importer/import_game.py"],
        @"--game",profile[@"game"],@"--destination",content,@"--resources",resources]];
    if(validate)[args addObject:@"--validate"];
    else { [args addObjectsFromArray:@[@"--source",source]];if(glide)[args addObjectsFromArray:@[@"--glide",glide]]; }
    task.arguments=args;
    NSMutableDictionary *env=[NSProcessInfo.processInfo.environment mutableCopy];
    [env removeObjectForKey:@"PYTHONPATH"];[env removeObjectForKey:@"__PYVENV_LAUNCHER__"];
    env[@"PYTHONHOME"]=[resources stringByAppendingPathComponent:@"Python"];
    env[@"PYTHONNOUSERSITE"]=@"1";env[@"PYTHONDONTWRITEBYTECODE"]=@"1";env[@"PYTHONUNBUFFERED"]=@"1";
    task.environment=env;task.standardOutput=[NSPipe pipe];task.standardError=NSFileHandle.fileHandleWithNullDevice;
    return task;
}
static NSDictionary *finishImportTask(NSTask *task, NSError *launchError) {
    if(launchError)return @{@"ok":@NO,@"error_code":@"runtime_missing",@"message":launchError.localizedDescription};
    NSData *data=[[(NSPipe *)task.standardOutput fileHandleForReading] readDataToEndOfFile];
    [task waitUntilExit];
    id value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
    if(![value isKindOfClass:NSDictionary.class])return @{@"ok":@NO,@"error_code":@"import_failed",@"message":@"The import could not finish. Choose a supported game installation and try again."};
    if(task.terminationStatus&&[value[@"ok"] boolValue])return @{@"ok":@NO,@"message":@"The import process stopped before completing."};
    return value;
}
static NSDictionary *runImport(NSString *resources, NSDictionary *profile, NSString *content,
                               NSString *source, NSString *glide, BOOL validate) {
    NSTask *task=importTask(resources,profile,content,source,glide,validate);NSError *error=nil;
    [task launchAndReturnError:&error];return finishImportTask(task,error);
}
static BOOL contentIsReady(NSString *resources, NSDictionary *profile, NSString *content) {
    NSDictionary *manifest=readJSON([content stringByAppendingPathComponent:@"manifest.json"]);
    if(![manifest[@"completed"] boolValue]||![manifest[@"game"] isEqual:profile[@"game"]])return NO;
    return [runImport(resources,profile,content,nil,nil,YES)[@"ok"] boolValue];
}

@interface FirstLaunchImport : NSObject<NSApplicationDelegate,NSWindowDelegate>
@property(strong) NSString *resources,*content,*source,*glide;
@property(strong) NSDictionary *profile;
@property(strong) NSWindow *window;
@property(strong) NSTextField *status;
@property(strong) NSButton *choose,*cancelButton;
@property(strong) NSProgressIndicator *progress;
@property(strong) NSTask *task;
@property BOOL completed,cancelled,needsGlide;
@end
@implementation FirstLaunchImport
- (NSTextField *)label:(NSString *)text frame:(NSRect)frame size:(CGFloat)size weight:(NSFontWeight)weight alpha:(CGFloat)alpha {
    NSTextField *label=[NSTextField wrappingLabelWithString:text];label.frame=frame;
    label.font=[NSFont systemFontOfSize:size weight:weight];label.textColor=[NSColor colorWithWhite:1 alpha:alpha];
    [self.window.contentView addSubview:label];return label;
}
- (void)cancel:(id)sender {
    (void)sender;self.cancelled=YES;
    if(self.task.running){[self.task terminate];[self.task waitUntilExit];}
    [NSApp stop:nil];
}
- (void)windowWillClose:(NSNotification *)note {(void)note;[self cancel:nil];}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {[self cancel:sender];return NSTerminateCancel;}
- (void)beginImport {
    self.choose.enabled=NO;self.status.stringValue=@"Copying and preparing your game files…\nThis may take a few minutes. Your original files will stay in place.";
    [self.progress startAnimation:nil];
    self.task=importTask(self.resources,self.profile,self.content,self.source,self.glide,NO);
    NSError *launchError=nil;[self.task launchAndReturnError:&launchError];NSTask *task=self.task;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
        NSDictionary *result=finishImportTask(task,launchError);
        dispatch_async(dispatch_get_main_queue(),^{
            if(self.cancelled)return;
            self.task=nil;[self.progress stopAnimation:nil];
            if([result[@"ok"] boolValue]){self.completed=YES;[NSApp stop:nil];return;}
            self.choose.enabled=YES;self.needsGlide=[result[@"error_code"] isEqual:@"missing_glide"];
            self.choose.title=self.needsGlide?@"Choose graphics driver…":@"Choose game files…";
            self.status.stringValue=result[@"message"]?:@"The game files could not be imported. Please choose another installation.";
        });
    });
}
- (void)chooseSource:(id)sender {
    (void)sender;NSOpenPanel *panel=[NSOpenPanel openPanel];
    panel.canChooseFiles=YES;panel.canChooseDirectories=YES;panel.allowsMultipleSelection=NO;
    panel.prompt=@"Import";
    panel.message=self.needsGlide?@"Select your owned Screamer Rally installation, or a compatible GLIDE2X.OVL file, for Screamer 2’s upgraded graphics.":@"Select your owned GOG .app, GOG .pkg or .dmg, or an extracted game installation folder.";
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response){
        if(response!=NSModalResponseOK)return;
        if(self.needsGlide)self.glide=panel.URL.path;
        else {self.source=panel.URL.path;self.glide=nil;}
        [self beginImport];
    }];
}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    (void)note;NSString *title=self.profile[@"title"]?:@"Screamer";
    NSMenu *menu=[NSMenu new],*appMenu=[NSMenu new];NSMenuItem *root=[NSMenuItem new];root.submenu=appMenu;[menu addItem:root];
    NSMenuItem *quit=[appMenu addItemWithTitle:[@"Quit " stringByAppendingString:title] action:@selector(cancel:) keyEquivalent:@"q"];quit.target=self;NSApp.mainMenu=menu;
    self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,900,570) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskFullSizeContentView backing:NSBackingStoreBuffered defer:NO];
    self.window.title=[title stringByAppendingString:@" — Import your game"];self.window.titleVisibility=NSWindowTitleHidden;self.window.titlebarAppearsTransparent=YES;
    self.window.releasedWhenClosed=NO;self.window.delegate=self;self.window.movableByWindowBackground=YES;self.window.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    SelectionBackground *background=[[SelectionBackground alloc] initWithFrame:NSMakeRect(0,0,900,570)];self.window.contentView=background;
    [self label:@"WELCOME" frame:NSMakeRect(56,484,388,18) size:11 weight:NSFontWeightSemibold alpha:.67];
    [self label:title frame:NSMakeRect(54,432,392,44) size:32 weight:NSFontWeightBold alpha:1];
    [self label:@"Import your game" frame:NSMakeRect(56,377,388,32) size:22 weight:NSFontWeightSemibold alpha:1];
    [self label:@"Choose your own copy to play Classic or Upgraded. Original game files are not included with this app." frame:NSMakeRect(56,285,388,78) size:16 weight:NSFontWeightRegular alpha:.86];
    self.status=[self label:@"Supports GOG macOS installers, installed apps, and extracted game folders." frame:NSMakeRect(56,166,388,104) size:13 weight:NSFontWeightRegular alpha:.72];
    self.progress=[[NSProgressIndicator alloc] initWithFrame:NSMakeRect(56,133,388,8)];self.progress.style=NSProgressIndicatorStyleBar;self.progress.indeterminate=YES;self.progress.displayedWhenStopped=NO;[background addSubview:self.progress];
    self.choose=[NSButton buttonWithTitle:@"Choose game files…" target:self action:@selector(chooseSource:)];self.choose.frame=NSMakeRect(217,61,227,38);self.choose.bezelStyle=NSBezelStyleRounded;self.choose.keyEquivalent=@"\r";[background addSubview:self.choose];
    self.cancelButton=[NSButton buttonWithTitle:@"Cancel" target:self action:@selector(cancel:)];self.cancelButton.frame=NSMakeRect(56,61,106,38);self.cancelButton.bezelStyle=NSBezelStyleRounded;self.cancelButton.keyEquivalent=@"\033";[background addSubview:self.cancelButton];
    [self.window center];[self.window makeKeyAndOrderFront:nil];
    if(@available(macOS 14.0,*))[NSApp activate];else [NSApp activateIgnoringOtherApps:YES];
}
@end
