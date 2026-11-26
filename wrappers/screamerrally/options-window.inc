#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

// The artwork is decoded original game data. Scaling and shading happen only
// while drawing this window; the bundled PNG retains all original pixels.
@interface ScreamerSelectionBackground : NSView
@property(nonatomic, strong) NSImage *image;
@property(nonatomic) BOOL panelOnRight;
@end

@implementation ScreamerSelectionBackground
- (void)drawRect:(NSRect)dirtyRect {
    (void)dirtyRect;
    [[NSColor colorWithSRGBRed:0.035 green:0.045 blue:0.06 alpha:1] setFill];
    NSRectFill(self.bounds);
    if (self.image && self.image.size.width > 0 && self.image.size.height > 0) {
        CGFloat scale = MAX(NSWidth(self.bounds)/self.image.size.width,
                            NSHeight(self.bounds)/self.image.size.height);
        NSSize size = NSMakeSize(self.image.size.width*scale, self.image.size.height*scale);
        NSRect destination = NSMakeRect((NSWidth(self.bounds)-size.width)/2,
                                       (NSHeight(self.bounds)-size.height)/2,
                                       size.width, size.height);
        NSGraphicsContext.currentContext.imageInterpolation = NSImageInterpolationHigh;
        [self.image drawInRect:destination fromRect:NSZeroRect
                    operation:NSCompositingOperationSourceOver fraction:1
               respectFlipped:YES hints:nil];
    }
    NSGradient *horizontal = [[NSGradient alloc]
        initWithStartingColor:[NSColor colorWithWhite:0 alpha:0.88]
                  endingColor:[NSColor colorWithWhite:0 alpha:0.10]];
    [horizontal drawInRect:self.bounds angle:self.panelOnRight ? 180 : 0];
    NSGradient *vertical = [[NSGradient alloc]
        initWithStartingColor:[NSColor colorWithWhite:0 alpha:0.28]
                  endingColor:[NSColor colorWithWhite:0 alpha:0]];
    [vertical drawInRect:self.bounds angle:90];

    NSBezierPath *panel = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(self.panelOnRight ? 403 : 32,32,425,452)
                                                       xRadius:16 yRadius:16];
    [[NSColor colorWithSRGBRed:0.035 green:0.045 blue:0.06 alpha:0.54] setFill];
    [panel fill];
    [[NSColor colorWithWhite:1 alpha:0.13] setStroke];
    panel.lineWidth = 1;
    [panel stroke];
}
@end

@interface ScreamerOptionsWindowController : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property(nonatomic, strong) NSMutableDictionary *settings;
@property(nonatomic, strong) NSDictionary *profile;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSButton *widescreenButton;
@property(nonatomic, strong) NSPopUpButton *distancePicker;
@property(nonatomic, strong) NSTextField *distanceHint;
@property(nonatomic, strong) NSButton *showOptionsButton;
@property(nonatomic) BOOL accepted;
@property(nonatomic) BOOL completed;
@end

@implementation ScreamerOptionsWindowController
- (NSTextField *)label:(NSString *)text frame:(NSRect)frame font:(NSFont *)font alpha:(CGFloat)alpha {
    NSTextField *label = [NSTextField wrappingLabelWithString:text];
    label.frame = frame;
    label.font = font;
    label.textColor = [NSColor colorWithWhite:1 alpha:alpha];
    [self.window.contentView addSubview:label];
    return label;
}

- (NSButton *)checkbox:(NSString *)title y:(CGFloat)y value:(BOOL)value {
    NSButton *button = [NSButton checkboxWithTitle:title target:nil action:nil];
    button.frame = NSMakeRect(60,y,365,26);
    button.font = [NSFont systemFontOfSize:14 weight:NSFontWeightMedium];
    button.contentTintColor = NSColor.whiteColor;
    button.state = value ? NSControlStateValueOn : NSControlStateValueOff;
    [self.window.contentView addSubview:button];
    return button;
}

- (void)updateDistanceHint {
    NSString *help = self.profile[@"distance_help"];
    BOOL rally = [self.profile[@"key"] isEqualToString:@"screamerrally"];
    if (rally && self.distancePicker.indexOfSelectedItem >= 2) {
        help = @"Farther is experimental. It may increase clipping or system load.";
    } else if (![help isKindOfClass:NSString.class] || !help.length) {
        help = @"Keep the original draw distance, or choose an extended view.";
    }
    self.distanceHint.stringValue = help;
    self.distanceHint.textColor = [NSColor colorWithWhite:1 alpha:0.70];
}

- (void)distanceChanged:(id)sender {
    (void)sender;
    [self updateDistanceHint];
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    NSString *title = self.profile[@"title"];
    if (![title isKindOfClass:NSString.class] || !title.length) title = @"Screamer";

    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Main Menu"];
    NSMenuItem *applicationItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    NSMenu *applicationMenu = [[NSMenu alloc] initWithTitle:title];
    NSMenuItem *quitItem = [[NSMenuItem alloc] initWithTitle:[@"Quit " stringByAppendingString:title]
                                                   action:@selector(terminate:)
                                            keyEquivalent:@"q"];
    quitItem.target = NSApp;
    [applicationMenu addItem:quitItem];
    applicationItem.submenu = applicationMenu;
    [menu addItem:applicationItem];
    NSApp.mainMenu = menu;

    self.window = [[NSWindow alloc]
        initWithContentRect:NSMakeRect(0,0,860,520)
                  styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskFullSizeContentView
                    backing:NSBackingStoreBuffered defer:NO];
    self.window.title = [title stringByAppendingString:@" Options"];
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.titlebarAppearsTransparent = YES;
    self.window.releasedWhenClosed = NO;
    self.window.delegate = self;
    self.window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    self.window.movableByWindowBackground = YES;
    ScreamerSelectionBackground *background = [[ScreamerSelectionBackground alloc]
        initWithFrame:NSMakeRect(0,0,860,520)];
    NSString *imagePath = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"SelectionBackground.png"];
    background.image = [[NSImage alloc] initWithContentsOfFile:imagePath];
    background.panelOnRight = [self.profile[@"key"] isEqualToString:@"screamerrally"];
    self.window.contentView = background;

    NSTextField *eyebrow = [self label:@"DISPLAY OPTIONS" frame:NSMakeRect(60,449,365,19)
                                 font:[NSFont systemFontOfSize:11 weight:NSFontWeightSemibold] alpha:0.65];
    eyebrow.attributedStringValue = [[NSAttributedString alloc] initWithString:@"DISPLAY OPTIONS"
        attributes:@{NSFontAttributeName:eyebrow.font, NSForegroundColorAttributeName:eyebrow.textColor,
                     NSKernAttributeName:@1.6}];
    [self label:title frame:NSMakeRect(58,398,370,46)
            font:[NSFont systemFontOfSize:32 weight:NSFontWeightBold] alpha:1];
    [self label:@"Set up your next race." frame:NSMakeRect(60,370,365,22)
            font:[NSFont systemFontOfSize:14] alpha:0.78];

    self.widescreenButton = [self checkbox:@"16:9 widescreen" y:320
                                    value:[self.settings[@"widescreen"] boolValue]];
    self.widescreenButton.accessibilityHelp = @"Shows more of the world. Menus and HUD stretch to the wider view.";
    [self label:@"Draw distance" frame:NSMakeRect(60,284,365,20)
            font:[NSFont systemFontOfSize:13 weight:NSFontWeightMedium] alpha:0.92];

    self.distancePicker = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(56,248,373,28) pullsDown:NO];
    self.distancePicker.font = [NSFont systemFontOfSize:13];
    NSArray *distanceOptions = self.profile[@"distance_options"];
    if (![distanceOptions isKindOfClass:NSArray.class] || !distanceOptions.count)
        distanceOptions = @[@"Original",@"Extended"];
    for (id option in distanceOptions) {
        if ([option isKindOfClass:NSString.class]) [self.distancePicker addItemWithTitle:option];
    }
    if (!self.distancePicker.numberOfItems) [self.distancePicker addItemWithTitle:@"Original"];
    NSInteger distanceLevel = self.settings[@"distance_level"] ? [self.settings[@"distance_level"] integerValue] :
        ([self.settings[@"extended_distance"] boolValue] ? 1 : 0);
    distanceLevel = MAX(0,MIN(distanceLevel,self.distancePicker.numberOfItems-1));
    [self.distancePicker selectItemAtIndex:distanceLevel];
    self.distancePicker.target = self;
    self.distancePicker.action = @selector(distanceChanged:);
    self.distancePicker.accessibilityLabel = @"Draw distance";
    [background addSubview:self.distancePicker];
    self.distanceHint = [self label:@"" frame:NSMakeRect(60,199,365,42)
                              font:[NSFont systemFontOfSize:12] alpha:0.70];
    [self updateDistanceHint];

    self.showOptionsButton = [self checkbox:@"Show options at launch" y:162
                                     value:[self.settings[@"show_options"] boolValue]];
    [self label:@"Widescreen expands the world; menus and HUD stretch. Hold Option while opening the app to change these choices."
           frame:NSMakeRect(60,108,365,44) font:[NSFont systemFontOfSize:12] alpha:0.70];

    NSButton *quit = [NSButton buttonWithTitle:@"Quit" target:self action:@selector(quit:)];
    quit.frame = NSMakeRect(230,56,88,32);
    quit.bezelStyle = NSBezelStyleRounded;
    quit.keyEquivalent = @"\033";
    [background addSubview:quit];
    NSButton *play = [NSButton buttonWithTitle:@"Play" target:self action:@selector(play:)];
    play.frame = NSMakeRect(330,56,100,32);
    play.bezelStyle = NSBezelStyleRounded;
    play.keyEquivalent = @"\r";
    [background addSubview:play];
    self.window.defaultButtonCell = play.cell;
    self.widescreenButton.nextKeyView = self.distancePicker;
    self.distancePicker.nextKeyView = self.showOptionsButton;
    self.showOptionsButton.nextKeyView = quit;
    quit.nextKeyView = play;
    play.nextKeyView = self.widescreenButton;
    self.window.initialFirstResponder = self.widescreenButton;

    // Keep Rally's car and Wales badge visible on the left of its loading art.
    if (background.panelOnRight) {
        for (NSView *view in background.subviews) {
            NSRect frame = view.frame;
            frame.origin.x += 371;
            view.frame = frame;
        }
    }
    [self.window center];
    [self.window makeKeyAndOrderFront:nil];
    if (@available(macOS 14.0,*)) [NSApp activate];
    else [NSApp activateIgnoringOtherApps:YES];
    [self.window displayIfNeeded];
}

- (void)finishWithAcceptance:(BOOL)accepted {
    if (self.completed) return;
    self.completed = YES;
    self.accepted = accepted;
    if (accepted) {
        NSInteger level = self.distancePicker.indexOfSelectedItem;
        self.settings[@"widescreen"] = @(self.widescreenButton.state == NSControlStateValueOn);
        self.settings[@"distance_level"] = @(level);
        self.settings[@"extended_distance"] = @(level > 0);
        self.settings[@"show_options"] = @(self.showOptionsButton.state == NSControlStateValueOn);
    }
    [self.window orderOut:nil];
    [NSApp stop:nil];
    [NSApp postEvent:[NSEvent otherEventWithType:NSEventTypeApplicationDefined
        location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0
        context:nil subtype:0 data1:0 data2:0] atStart:NO];
}
- (void)play:(id)sender { (void)sender; [self finishWithAcceptance:YES]; }
- (void)quit:(id)sender { (void)sender; [self finishWithAcceptance:NO]; }
- (BOOL)windowShouldClose:(NSWindow *)sender {
    (void)sender; [self finishWithAcceptance:NO]; return NO;
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender; [self finishWithAcceptance:NO]; return NSTerminateCancel;
}
@end

static BOOL chooseOptions(NSMutableDictionary *settings, NSDictionary *profile) {
    NSApplication *application = [NSApplication sharedApplication];
    [application setActivationPolicy:NSApplicationActivationPolicyRegular];
    ScreamerOptionsWindowController *controller = [[ScreamerOptionsWindowController alloc] init];
    controller.settings = settings;
    controller.profile = profile;
    application.delegate = controller;
    [application run];
    application.delegate = nil;
    controller.window.delegate = nil;
    [controller.window close];
    return controller.accepted;
}
