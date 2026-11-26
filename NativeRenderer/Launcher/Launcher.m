#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <unistd.h>

// The parent never initializes NSApplication: the options helper exits before
// exec starts either game. SDL/AppKit must register a fresh application instance.
static NSDictionary *readJSON(NSString *path) {
    NSData *data=[NSData dataWithContentsOfFile:path];
    id value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
    return [value isKindOfClass:NSDictionary.class]?value:@{};
}
static NSMutableDictionary *options(NSDictionary *saved) {
    NSMutableDictionary *result=[@{@"mode":@"upgraded"} mutableCopy];
    if([@[@"classic",@"upgraded"] containsObject:saved[@"mode"]])result[@"mode"]=saved[@"mode"];
    return result;
}

@interface SelectionBackground : NSView
@property(strong) NSImage *image;
@property BOOL panelOnRight;
@end
@implementation SelectionBackground
- (void)drawRect:(NSRect)rect {
    (void)rect;[[NSColor colorWithWhite:.035 alpha:1] setFill];NSRectFill(self.bounds);
    CGFloat scale=MAX(self.bounds.size.width/self.image.size.width,self.bounds.size.height/self.image.size.height);
    if(self.image&&isfinite(scale)&&scale>0){
        NSSize size=NSMakeSize(self.image.size.width*scale,self.image.size.height*scale);
        NSGraphicsContext.currentContext.imageInterpolation=NSImageInterpolationHigh;
        [self.image drawInRect:NSMakeRect((self.bounds.size.width-size.width)/2,(self.bounds.size.height-size.height)/2,size.width,size.height) fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1];
    }
    NSGradient *shade=[[NSGradient alloc] initWithStartingColor:[NSColor colorWithWhite:0 alpha:.9] endingColor:[NSColor colorWithWhite:0 alpha:.08]];
    [shade drawInRect:self.bounds angle:self.panelOnRight?180:0];
    NSBezierPath *panel=[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(self.panelOnRight?430:30,28,440,514) xRadius:18 yRadius:18];
    [[NSColor colorWithWhite:.025 alpha:.7] setFill];[panel fill];
    [[NSColor colorWithWhite:1 alpha:.16] setStroke];[panel stroke];
}
@end

#import "FirstLaunchImport.inc"

@interface GameSelection : NSObject<NSApplicationDelegate,NSWindowDelegate>
@property(strong) NSString *resources,*output;
@property(strong) NSMutableDictionary *settings;
@property(strong) NSWindow *window;
@property(strong) NSSegmentedControl *mode;
@property(strong) NSTextField *explanation,*featureSummary;
@property BOOL accepted;
@end
@implementation GameSelection
- (NSTextField *)label:(NSString *)text frame:(NSRect)frame size:(CGFloat)size weight:(NSFontWeight)weight alpha:(CGFloat)alpha {
    NSTextField *label=[NSTextField wrappingLabelWithString:text];label.frame=frame;
    label.font=[NSFont systemFontOfSize:size weight:weight];label.textColor=[NSColor colorWithWhite:1 alpha:alpha];
    [self.window.contentView addSubview:label];return label;
}
- (void)modeChanged:(id)sender {
    (void)sender;BOOL upgraded=self.mode.selectedSegment==1;
    self.explanation.stringValue=upgraded?@"High resolution at your window or display’s pixel size.":@"The original graphics and presentation.";
    NSString *features=upgraded?@"High-resolution graphics\n16:9 widescreen — a wider view\nFull-track draw distance":@"Original graphics\nOriginal 4:3 view\nOriginal draw distance";
    NSMutableParagraphStyle *paragraph=[NSMutableParagraphStyle new];paragraph.lineSpacing=10;
    self.featureSummary.attributedStringValue=[[NSAttributedString alloc] initWithString:features attributes:@{NSFontAttributeName:self.featureSummary.font,NSForegroundColorAttributeName:self.featureSummary.textColor,NSParagraphStyleAttributeName:paragraph}];
}
- (void)start:(id)sender {
    (void)sender;self.settings=options(@{@"mode":self.mode.selectedSegment==1?@"upgraded":@"classic"});
    self.settings[@"selection_accepted"]=@YES;
    NSData *data=[NSJSONSerialization dataWithJSONObject:self.settings options:NSJSONWritingPrettyPrinted error:nil];
    self.accepted=[data writeToFile:self.output atomically:YES];[NSApp stop:nil];
}
- (void)cancel:(id)sender {(void)sender;[NSApp stop:nil];}
- (void)windowWillClose:(NSNotification *)note {(void)note;[NSApp stop:nil];}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {[self cancel:sender];return NSTerminateCancel;}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    (void)note;NSDictionary *profile=readJSON([self.resources stringByAppendingPathComponent:@"SelectionConfig.json"]);
    NSString *title=profile[@"title"]?:@"Screamer";
    NSMenu *menu=[NSMenu new],*appMenu=[NSMenu new];NSMenuItem *root=[NSMenuItem new];root.submenu=appMenu;[menu addItem:root];
    NSMenuItem *quit=[appMenu addItemWithTitle:[@"Quit " stringByAppendingString:title] action:@selector(cancel:) keyEquivalent:@"q"];quit.target=self;NSApp.mainMenu=menu;
    self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,900,570) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskFullSizeContentView backing:NSBackingStoreBuffered defer:NO];
    self.window.title=[title stringByAppendingString:@" — Choose your experience"];self.window.titleVisibility=NSWindowTitleHidden;self.window.titlebarAppearsTransparent=YES;
    self.window.releasedWhenClosed=NO;self.window.delegate=self;self.window.movableByWindowBackground=YES;self.window.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    SelectionBackground *background=[[SelectionBackground alloc] initWithFrame:NSMakeRect(0,0,900,570)];
    NSString *content=NSProcessInfo.processInfo.environment[@"SCREAMER_CONTENT_ROOT"];
    NSString *artwork=[self.resources stringByAppendingPathComponent:@"SelectionBackground.png"];
    if(content.length)artwork=[content stringByAppendingPathComponent:@"SelectionBackground.png"];
    background.image=[[NSImage alloc] initWithContentsOfFile:artwork];
    background.panelOnRight=[profile[@"game"] isEqual:@"screamerrally"];self.window.contentView=background;
    CGFloat x=background.panelOnRight?456:56;
    [self label:@"CHOOSE YOUR EXPERIENCE" frame:NSMakeRect(x,484,388,18) size:11 weight:NSFontWeightSemibold alpha:.67];
    [self label:title frame:NSMakeRect(x-2,432,392,44) size:32 weight:NSFontWeightBold alpha:1];
    self.mode=[NSSegmentedControl segmentedControlWithLabels:@[@"Classic",@"Upgraded"] trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(modeChanged:)];
    self.mode.frame=NSMakeRect(x,382,388,32);self.mode.selectedSegment=[self.settings[@"mode"] isEqual:@"classic"]?0:1;[background addSubview:self.mode];
    self.explanation=[self label:@"" frame:NSMakeRect(x,327,388,44) size:14 weight:NSFontWeightRegular alpha:.78];
    self.featureSummary=[self label:@"" frame:NSMakeRect(x,195,388,112) size:16 weight:NSFontWeightMedium alpha:.95];
    [self label:@"Original game physics in both modes." frame:NSMakeRect(x,129,388,35) size:12 weight:NSFontWeightRegular alpha:.65];
    NSButton *start=[NSButton buttonWithTitle:@"Start game" target:self action:@selector(start:)];start.frame=NSMakeRect(x+218,61,170,38);start.bezelStyle=NSBezelStyleRounded;start.keyEquivalent=@"\r";[background addSubview:start];
    NSButton *cancel=[NSButton buttonWithTitle:@"Cancel" target:self action:@selector(cancel:)];cancel.frame=NSMakeRect(x,61,106,38);cancel.bezelStyle=NSBezelStyleRounded;cancel.keyEquivalent=@"\033";[background addSubview:cancel];
    [self modeChanged:nil];[self.window center];[self.window makeKeyAndOrderFront:nil];
    if(@available(macOS 14.0,*))[NSApp activate];else [NSApp activateIgnoringOtherApps:YES];
}
@end

static int failure(NSString *message) {fprintf(stderr,"Game launcher: %s\n",message.UTF8String);return 1;}
int main(int argc,const char **argv) {
    @autoreleasepool {
        if(argc==4&&!strcmp(argv[1],"--import-helper")){
            [NSApplication sharedApplication];NSApp.activationPolicy=NSApplicationActivationPolicyRegular;
            FirstLaunchImport *importer=[FirstLaunchImport new];importer.resources=[NSString stringWithUTF8String:argv[2]];
            importer.content=[NSString stringWithUTF8String:argv[3]];importer.profile=readJSON([importer.resources stringByAppendingPathComponent:@"SelectionConfig.json"]);
            NSApp.delegate=importer;[NSApp run];return importer.completed?0:2;
        }
        if(argc==4&&!strcmp(argv[1],"--settings-helper")){
            [NSApplication sharedApplication];NSApp.activationPolicy=NSApplicationActivationPolicyRegular;
            GameSelection *selection=[GameSelection new];selection.resources=[NSString stringWithUTF8String:argv[2]];selection.output=[NSString stringWithUTF8String:argv[3]];selection.settings=options(readJSON(selection.output));
            NSApp.delegate=selection;[NSApp run];return selection.accepted?0:2;
        }
        NSString *resources=NSBundle.mainBundle.resourcePath;NSDictionary *profile=readJSON([resources stringByAppendingPathComponent:@"SelectionConfig.json"]);
        if(!profile.count)return failure(@"The game selection configuration is missing.");
        if(![@[@"screamer",@"screamer2",@"screamerrally"] containsObject:profile[@"game"]]||![profile[@"support_name"] isKindOfClass:NSString.class]||![profile[@"support_name"] length]||[profile[@"support_name"] containsString:@"/"]||[@[@".",@".."] containsObject:profile[@"support_name"]])return failure(@"The game configuration is invalid.");
        NSString *support=[NSHomeDirectory() stringByAppendingPathComponent:[@"Library/Application Support" stringByAppendingPathComponent:profile[@"support_name"]]];
        NSString *settingsPath=[support stringByAppendingPathComponent:@"LaunchOptions.json"];
        NSMutableDictionary *settings=options(readJSON(settingsPath));BOOL show=YES,dryRun=NO,validateImport=NO;
        NSString *importSource=nil,*glide=nil,*explicitMode=nil;
        for(int i=1;i<argc;i++){
            if(!strcmp(argv[i],"--no-settings"))show=NO;
            else if(!strcmp(argv[i],"--classic")){explicitMode=@"classic";show=NO;}
            else if(!strcmp(argv[i],"--upgraded")){explicitMode=@"upgraded";show=NO;}
            else if(!strcmp(argv[i],"--dry-run")){dryRun=YES;show=NO;}
            else if(!strcmp(argv[i],"--validate-import")){validateImport=YES;show=NO;}
            else if(!strcmp(argv[i],"--import-source")||!strcmp(argv[i],"--glide")||!strcmp(argv[i],"--support-directory")){
                NSString *flag=[NSString stringWithUTF8String:argv[i]];if(i+1>=argc)return failure(@"Missing launcher argument.");
                NSString *value=[NSString stringWithUTF8String:argv[++i]];
                if([flag isEqual:@"--import-source"])importSource=value;
                else if([flag isEqual:@"--glide"])glide=value;
                else {if(!value.isAbsolutePath)return failure(@"The support directory must be an absolute path.");support=value;settingsPath=[support stringByAppendingPathComponent:@"LaunchOptions.json"];}
            }
            else return failure(@"Unknown launcher argument.");
        }
        if((dryRun&&(importSource||validateImport))||(validateImport&&(importSource||glide)))return failure(@"Choose one import or dry-run operation at a time.");
        settings=options(readJSON(settingsPath));if(explicitMode)settings[@"mode"]=explicitMode;
        BOOL requiresImport=[profile[@"requires_import"] boolValue];NSString *content=[support stringByAppendingPathComponent:@"Content"];
        if(importSource||validateImport){
            if(!requiresImport)return failure(@"This app includes local game data and does not use the import flow.");
            NSDictionary *result=runImport(resources,profile,content,importSource,glide,validateImport);
            NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];fwrite(data.bytes,1,data.length,stdout);fputc('\n',stdout);
            return [result[@"ok"] boolValue]?0:1;
        }
        if(glide)return failure(@"Use --glide together with --import-source.");
        if(requiresImport){
            BOOL ready=contentIsReady(resources,profile,content);
            if(!ready&&dryRun){NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"import_required":@YES,@"game":profile[@"game"],@"content_root":content} options:NSJSONWritingPrettyPrinted error:nil];fwrite(data.bytes,1,data.length,stdout);fputc('\n',stdout);return 0;}
            if(!ready){
                NSTask *helper=[NSTask new];helper.executableURL=[NSURL fileURLWithPath:[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"Contents/Helpers/Game Selection.app/Contents/MacOS/GameSelection"]];
                helper.arguments=@[@"--import-helper",resources,content];NSError *error=nil;
                if(![helper launchAndReturnError:&error])return failure(error.localizedDescription);
                [helper waitUntilExit];if(helper.terminationStatus==2)return 0;
                if(helper.terminationStatus||!contentIsReady(resources,profile,content))return failure(@"The game import could not complete.");
            }
            if(setenv("SCREAMER_CONTENT_ROOT",content.fileSystemRepresentation,1)||setenv("SCREAMER_SUPPORT_DIRECTORY",support.fileSystemRepresentation,1))return failure(@"Cannot set the imported game directory.");
        }
        if(show){
            NSError *error=nil;NSFileManager *fm=NSFileManager.defaultManager;
            if(![fm createDirectoryAtPath:support withIntermediateDirectories:YES attributes:nil error:&error])return failure(error.localizedDescription);
            NSString *pending=[NSTemporaryDirectory() stringByAppendingPathComponent:[@"screamer-selection-" stringByAppendingString:NSUUID.UUID.UUIDString]];
            NSData *initial=[NSJSONSerialization dataWithJSONObject:settings options:0 error:nil];
            if(![initial writeToFile:pending atomically:YES])return failure(@"Cannot create temporary game options.");
            NSTask *helper=[NSTask new];helper.executableURL=[NSURL fileURLWithPath:[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"Contents/Helpers/Game Selection.app/Contents/MacOS/GameSelection"]];helper.arguments=@[@"--settings-helper",resources,pending];
            if(![helper launchAndReturnError:&error]){[fm removeItemAtPath:pending error:nil];return failure(error.localizedDescription);}
            [helper waitUntilExit];NSDictionary *chosen=readJSON(pending);[fm removeItemAtPath:pending error:nil];
            if(helper.terminationStatus==2)return 0;
            if(helper.terminationStatus||![chosen[@"selection_accepted"] boolValue])return failure(@"The game selection window could not complete.");
            settings=options(chosen);NSData *data=[NSJSONSerialization dataWithJSONObject:settings options:NSJSONWritingPrettyPrinted error:nil];
            if(![data writeToFile:settingsPath atomically:YES])return failure(@"Cannot save game options.");
        }
        NSString *executable;NSArray<NSString *> *arguments;
        if([settings[@"mode"] isEqual:@"classic"]){
            executable=[resources stringByAppendingPathComponent:@"Classic/Game.app/Contents/MacOS/GameLauncher"];
            arguments=@[@"--no-settings",@"--original-aspect",@"--distance-level",@"0"];
        }else{
            executable=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"Contents/MacOS/RallyMetalPreview"];
            arguments=@[@"--window-resolution",@"--widescreen",@"--extended-distance"];
        }
        if(![NSFileManager.defaultManager isExecutableFileAtPath:executable])return failure(@"The selected game runtime is missing.");
        if(dryRun){NSMutableDictionary *result=[@{@"executable":executable,@"arguments":arguments,@"settings":settings} mutableCopy];if(requiresImport){result[@"content_root"]=content;result[@"import_required"]=@NO;}NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];fwrite(data.bytes,1,data.length,stdout);fputc('\n',stdout);return 0;}
        char **args=calloc(arguments.count+2,sizeof(char *));if(!args)return failure(@"Cannot start the game.");args[0]=(char *)executable.fileSystemRepresentation;
        for(NSUInteger i=0;i<arguments.count;i++)args[i+1]=(char *)arguments[i].UTF8String;
        execv(args[0],args);free(args);return failure(@"The selected game runtime could not start.");
    }
}
