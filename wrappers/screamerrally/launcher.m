#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <unistd.h>

static int fail(NSString *message, BOOL consoleOnly) {
    fprintf(stderr, "%s\n", message.UTF8String);
    if (!consoleOnly) {
        [NSApplication sharedApplication];
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"The game could not start";
        alert.informativeText = message;
        [alert addButtonWithTitle:@"OK"];
        [alert runModal];
    }
    return 1;
}

static BOOL safeConfigPath(NSString *path) {
    return [path rangeOfCharacterFromSet:
        [NSCharacterSet characterSetWithCharactersInString:@"\"\r\n"]].location == NSNotFound;
}

static NSString *sha256(NSData *data) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *result = [NSMutableString stringWithCapacity:64];
    for (NSUInteger i = 0; i < sizeof(digest); ++i) [result appendFormat:@"%02x", digest[i]];
    return result;
}

#include "options-window.inc"

// Only derived launch executables are patched. The bundled and writable originals
// and all save files remain untouched, including when toggles change later.
static NSString *prepareEnhancedProgram(NSDictionary *enhancements, NSString *source,
                                        NSString *game, BOOL wide, NSInteger distanceLevel,
                                        NSError **error) {
    NSString *original = enhancements[@"original"];
    NSString *derived = enhancements[@"derived"];
    NSData *clean = [NSData dataWithContentsOfFile:[source stringByAppendingPathComponent:original]
                                          options:0 error:error];
    if (!clean) return nil;
    if (![sha256(clean) isEqualToString:enhancements[@"sha256"]]) {
        *error = [NSError errorWithDomain:@"ScreamerWrapper" code:1 userInfo:
            @{NSLocalizedDescriptionKey: @"The bundled game executable does not match the supported version. No patches were applied."}];
        return nil;
    }
    NSMutableData *patched = [clean mutableCopy];
    for (NSDictionary *patch in enhancements[@"patches"]) {
        BOOL isWide = [patch[@"option"] isEqualToString:@"widescreen"];
        BOOL compatibility = [patch[@"option"] isEqualToString:@"compatibility"];
        BOOL enabled = compatibility || (isWide ? wide : distanceLevel > 0);
        if (!enabled) continue;
        NSUInteger offset = [patch[@"offset"] unsignedIntegerValue];
        NSData *expected = [[NSData alloc] initWithBase64EncodedString:patch[@"expected"] options:0];
        NSDictionary *choices = patch[@"replacements"];
        NSString *encoded = compatibility ? patch[@"replacement"] :
            !isWide && choices ? choices[[@(distanceLevel) stringValue]] :
            (!isWide && distanceLevel == 2 ? patch[@"replacement_farther"] : patch[@"replacement"]);
        NSData *replacement = encoded ? [[NSData alloc] initWithBase64EncodedString:encoded options:0] : nil;
        if (!expected.length || expected.length != replacement.length ||
            offset > patched.length || expected.length > patched.length - offset ||
            memcmp((const unsigned char *)patched.bytes + offset, expected.bytes, expected.length)) {
            *error = [NSError errorWithDomain:@"ScreamerWrapper" code:2 userInfo:
                @{NSLocalizedDescriptionKey: @"A game patch failed its original-byte check. No launch executable was written."}];
            return nil;
        }
        [patched replaceBytesInRange:NSMakeRange(offset, expected.length) withBytes:replacement.bytes];
    }
    if (![patched writeToFile:[game stringByAppendingPathComponent:derived] options:NSDataWritingAtomic error:error])
        return nil;
    return derived;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        // Keep AppKit's application lifecycle in a separate short-lived process.
        // Initializing NSApplication here and then exec'ing SDL leaves macOS's
        // window/accessibility registration tied to the old application instance.
        if ([NSBundle.mainBundle.bundleIdentifier hasSuffix:@".options"] &&
            !(argc == 4 && !strcmp(argv[1], "--options-helper"))) return 0;
        if (argc == 4 && !strcmp(argv[1], "--options-helper")) {
            NSString *path = [NSString stringWithUTF8String:argv[2]];
            NSData *data = [NSData dataWithContentsOfFile:path];
            id decoded = data ? [NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingMutableContainers error:nil] : nil;
            if (![decoded isKindOfClass:NSMutableDictionary.class]) return 1;
                        NSData *profileData = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[3]]];
            id helperProfile = profileData ? [NSJSONSerialization JSONObjectWithData:profileData options:0 error:nil] : nil;
            if (![helperProfile isKindOfClass:NSDictionary.class]) return 1;
            if (!chooseOptions(decoded, helperProfile)) return 2;
            NSData *result = [NSJSONSerialization dataWithJSONObject:decoded options:NSJSONWritingPrettyPrinted error:nil];
            return result && [result writeToFile:path atomically:YES] ? 0 : 1;
        }
        BOOL prepareOnly = NO, windowed = NO, forceSettings = NO, noSettings = NO;
        NSNumber *wideOverride = nil, *distanceOverride = nil;
        NSString *dataOverride = nil;
        for (int i = 1; i < argc; ++i) {
            if (!strcmp(argv[i], "--prepare-only")) prepareOnly = YES;
            else if (!strcmp(argv[i], "--windowed")) windowed = YES;
            else if (!strcmp(argv[i], "--settings")) forceSettings = YES;
            else if (!strcmp(argv[i], "--no-settings")) noSettings = YES;
            else if (!strcmp(argv[i], "--widescreen")) wideOverride = @YES;
            else if (!strcmp(argv[i], "--original-aspect")) wideOverride = @NO;
            else if (!strcmp(argv[i], "--extended-distance")) distanceOverride = @1;
            else if (!strcmp(argv[i], "--farther-distance")) distanceOverride = @2;
            else if (!strcmp(argv[i], "--standard-distance")) distanceOverride = @0;
            else if (!strcmp(argv[i], "--distance-level") && i + 1 < argc) {
                const char *text = argv[++i];
                char *end = NULL;
                long level = strtol(text, &end, 10);
                if (!*text || *end || level < 0 || level > 3)
                    return fail(@"Invalid draw-distance level.", YES);
                distanceOverride = @(level);
            }
            else if (!strcmp(argv[i], "--data-dir") && i + 1 < argc)
                dataOverride = [NSString stringWithUTF8String:argv[++i]];
            else return fail(@"Unknown launcher argument.", YES);
        }

        NSBundle *bundle = NSBundle.mainBundle;
        NSFileManager *fm = NSFileManager.defaultManager;
        NSString *resources = bundle.resourcePath;
        NSData *profileData = [NSData dataWithContentsOfFile:
            [resources stringByAppendingPathComponent:@"game-profile.json"]];
        NSError *error = nil;
        NSDictionary *profile = profileData ? [NSJSONSerialization JSONObjectWithData:profileData options:0 error:&error] : nil;
        if (![profile isKindOfClass:NSDictionary.class])
            return fail(@"The bundled game profile is missing or invalid.", prepareOnly);

        NSString *key = profile[@"key"];
        NSString *title = profile[@"title"];
        NSString *program = profile[@"program"];
        NSString *cue = profile[@"cue"];
        NSString *image = profile[@"image"];
        NSArray *readOnlyEntries = profile[@"readonly_entries"];
        NSDictionary *enhancements = profile[@"enhancements"];
        NSString *template = [NSString stringWithContentsOfFile:
            [resources stringByAppendingPathComponent:@"game.conf.in"]
            encoding:NSUTF8StringEncoding error:&error];
        if (!key || !title || !program || !cue || !image || !template)
            return fail(@"The game bundle is incomplete.", prepareOnly);
        if (!enhancements && (forceSettings || wideOverride || distanceOverride))
            return fail(@"This game bundle does not support optional Rally enhancements.", YES);

        NSURL *supportURL = [fm URLForDirectory:NSApplicationSupportDirectory inDomain:NSUserDomainMask
                              appropriateForURL:nil create:NO error:&error];
        NSString *supportOverride = NSProcessInfo.processInfo.environment[@"SCREAMER_SUPPORT_DIRECTORY"];
        NSString *dataRoot = dataOverride ? dataOverride.stringByStandardizingPath :
            (supportOverride.length ? [supportOverride stringByAppendingPathComponent:@"ClassicData"] :
             [[supportURL.path stringByAppendingPathComponent:@"Screamer Native"] stringByAppendingPathComponent:key]);
        if (![dataRoot isAbsolutePath] || !safeConfigPath(dataRoot) || !safeConfigPath(resources))
            return fail(@"The game and save-folder paths must be absolute and cannot contain quotation marks or line breaks.", prepareOnly);
        if (![fm createDirectoryAtPath:dataRoot withIntermediateDirectories:YES attributes:nil error:&error])
            return fail([NSString stringWithFormat:@"Cannot create the save folder: %@", error.localizedDescription], prepareOnly);

        // Keep the lock across exec, so a second process cannot write the same saves.
        int lockFD = open([[dataRoot stringByAppendingPathComponent:@".running.lock"] fileSystemRepresentation], O_CREAT | O_RDWR, 0600);
        if (lockFD < 0 || flock(lockFD, LOCK_EX | LOCK_NB) != 0)
            return fail([NSString stringWithFormat:@"%@ is already running, or its save folder is unavailable.", title], prepareOnly);

        NSMutableDictionary *settings = [@{@"widescreen":@NO, @"extended_distance":@NO, @"distance_level":@0, @"show_options":@YES} mutableCopy];
        NSString *settingsPath = [dataRoot stringByAppendingPathComponent:@"settings.json"];
        if (enhancements && [fm fileExistsAtPath:settingsPath]) {
            NSData *saved = [NSData dataWithContentsOfFile:settingsPath options:0 error:&error];
            id decoded = saved ? [NSJSONSerialization JSONObjectWithData:saved options:0 error:&error] : nil;
            if (![decoded isKindOfClass:NSDictionary.class])
                return fail(@"Cannot read settings.json in the game's support folder. Move that file aside to restore default options.", prepareOnly);
            for (NSString *name in settings.allKeys) {
                id value = decoded[name];
                if (value && ![value isKindOfClass:NSNumber.class])
                    return fail(@"A game option in settings.json is invalid.", prepareOnly);
                if (value) settings[name] = [name isEqualToString:@"distance_level"] ? @([value integerValue]) : @([value boolValue]);
            }
            if (!decoded[@"distance_level"])
                settings[@"distance_level"] = @([settings[@"extended_distance"] boolValue] ? 1 : 0);
        }
        if (wideOverride) settings[@"widescreen"] = wideOverride;
        if (distanceOverride) settings[@"distance_level"] = distanceOverride;
        NSInteger selectedDistance = [settings[@"distance_level"] integerValue];
        NSArray *distanceOptions = profile[@"distance_options"];
        if (selectedDistance < 0 || selectedDistance >= (NSInteger)distanceOptions.count)
            return fail(@"This draw-distance setting is not supported by this game.", prepareOnly);
        settings[@"extended_distance"] = @(selectedDistance > 0);
        BOOL optionHeld = !prepareOnly && (NSEvent.modifierFlags & NSEventModifierFlagOption) != 0;
        BOOL showSettings = enhancements && !prepareOnly && !noSettings &&
            (forceSettings || optionHeld || (!wideOverride && !distanceOverride && [settings[@"show_options"] boolValue]));
        if (showSettings) {
            NSString *pending = [dataRoot stringByAppendingPathComponent:
                [NSString stringWithFormat:@".options-%@.json", NSUUID.UUID.UUIDString]];
            NSData *initial = [NSJSONSerialization dataWithJSONObject:settings options:0 error:&error];
            if (!initial || ![initial writeToFile:pending options:NSDataWritingAtomic error:&error])
                return fail(error.localizedDescription, NO);
            NSTask *task = [[NSTask alloc] init];
            task.executableURL = [NSURL fileURLWithPath:[bundle.bundlePath stringByAppendingPathComponent:
                @"Contents/Helpers/Game Options.app/Contents/MacOS/GameOptions"]];
            task.arguments = @[@"--options-helper", pending, [resources stringByAppendingPathComponent:@"game-profile.json"]];
            if (![task launchAndReturnError:&error]) {
                [fm removeItemAtPath:pending error:nil];
                return fail([NSString stringWithFormat:@"Cannot open the game options: %@", error.localizedDescription], NO);
            }
            [task waitUntilExit];
            NSData *chosen = [NSData dataWithContentsOfFile:pending];
            [fm removeItemAtPath:pending error:nil];
            if (task.terminationReason == NSTaskTerminationReasonExit && task.terminationStatus == 2) return 0;
            id decoded = chosen ? [NSJSONSerialization JSONObjectWithData:chosen options:NSJSONReadingMutableContainers error:&error] : nil;
            if (task.terminationStatus != 0 || ![decoded isKindOfClass:NSMutableDictionary.class])
                return fail(@"The game options window could not complete.", NO);
            settings = decoded;
            if (![chosen writeToFile:settingsPath options:NSDataWritingAtomic error:&error])
                return fail([NSString stringWithFormat:@"Cannot save game options: %@", error.localizedDescription], NO);
        }
        BOOL wide = [settings[@"widescreen"] boolValue];
        NSInteger distanceLevel = [settings[@"distance_level"] integerValue];

        NSString *content = NSProcessInfo.processInfo.environment[@"SCREAMER_CONTENT_ROOT"] ?: resources;
        if (![content isAbsolutePath] || !safeConfigPath(content))
            return fail(@"The imported game folder must be absolute and cannot contain quotation marks or line breaks.", prepareOnly);
        NSString *source = [content stringByAppendingPathComponent:@"game"];
        NSString *disc = [source stringByAppendingPathComponent:cue];
        NSString *discImage = [source stringByAppendingPathComponent:image];
        if (![fm isReadableFileAtPath:disc] || ![fm isReadableFileAtPath:discImage])
            return fail(@"The imported CD image is missing. Import the game files again.", prepareOnly);

        NSString *game = [dataRoot stringByAppendingPathComponent:@"Game"];
        BOOL isDirectory = NO;
        if (![fm fileExistsAtPath:game isDirectory:&isDirectory]) {
            NSString *staging = [dataRoot stringByAppendingPathComponent:
                [@"Game.installing-" stringByAppendingString:NSUUID.UUID.UUIDString]];
            if (![fm createDirectoryAtPath:staging withIntermediateDirectories:NO attributes:nil error:&error])
                return fail(error.localizedDescription, prepareOnly);
            NSArray<NSString *> *entries = [fm contentsOfDirectoryAtPath:source error:&error];
            if (!entries) return fail(error.localizedDescription, prepareOnly);
            for (NSString *name in entries) {
                if ([name isEqualToString:cue] || [name isEqualToString:image] ||
                    [readOnlyEntries containsObject:name] ||
                    [name.lowercaseString hasPrefix:@"dosbox"] ||
                    [name.pathExtension.lowercaseString isEqualToString:@"pdf"]) continue;
                if (![fm copyItemAtPath:[source stringByAppendingPathComponent:name]
                                toPath:[staging stringByAppendingPathComponent:name] error:&error])
                    return fail([NSString stringWithFormat:@"Cannot prepare the game files: %@", error.localizedDescription], prepareOnly);
            }
            if (![fm moveItemAtPath:staging toPath:game error:&error])
                return fail(error.localizedDescription, prepareOnly);
        } else if (!isDirectory) {
            return fail(@"The game's save location exists but is not a folder.", prepareOnly);
        }
        if (![fm isReadableFileAtPath:[game stringByAppendingPathComponent:program]])
            return fail(@"The game executable is missing from its writable game folder.", prepareOnly);

        NSString *dosCommand = profile[@"dos_command"] ?: program;
        if (enhancements && (wide || distanceLevel > 0 || [enhancements[@"always_apply"] boolValue])) {
            program = prepareEnhancedProgram(enhancements, source, game, wide, distanceLevel, &error);
            if (!program) return fail(error.localizedDescription, prepareOnly);
            NSString *directory = program.stringByDeletingLastPathComponent;
            dosCommand = directory.length ? [NSString stringWithFormat:@"cd %@\n%@", directory, program.lastPathComponent] : program.lastPathComponent;
        }
        NSString *config = [template stringByReplacingOccurrencesOfString:@"@DISC_CUE@" withString:disc];
        config = [config stringByReplacingOccurrencesOfString:@"@FULLSCREEN@" withString:windowed ? @"false" : @"true"];
        config = [config stringByReplacingOccurrencesOfString:@"@WINDOW_SIZE@" withString:wide ? @"1280x720" : @"1280x960"];
        config = [config stringByReplacingOccurrencesOfString:@"@ASPECT@" withString:wide ? @"stretch" : @"on"];
        config = [config stringByReplacingOccurrencesOfString:@"@SHADER@" withString:wide ? @"trilogy-widescreen" : @"sharp"];
        config = [config stringByReplacingOccurrencesOfString:@"@PROGRAM@" withString:dosCommand];
        NSString *configPath = [dataRoot stringByAppendingPathComponent:@"dosbox.conf"];
        if (![config writeToFile:configPath atomically:YES encoding:NSUTF8StringEncoding error:&error])
            return fail(error.localizedDescription, prepareOnly);

        NSString *engine = [bundle.bundlePath stringByAppendingPathComponent:@"Contents/MacOS/dosbox"];
        if (![fm isExecutableFileAtPath:engine]) return fail(@"The native DOSBox runtime is missing.", prepareOnly);
        if (prepareOnly) {
            printf("Game: %s\nRuntime: %s\nData: %s\nConfig: %s\nProgram: %s\nWidescreen: %s\nExtended distance: %s\n", title.UTF8String,
                   engine.UTF8String, game.UTF8String, configPath.UTF8String, program.UTF8String,
                   wide ? "on" : "off", [[profile[@"distance_options"] objectAtIndex:(NSUInteger)distanceLevel] UTF8String]);
            return 0;
        }

        NSString *logPath = [dataRoot stringByAppendingPathComponent:@"runtime.log"];
        int logFD = open(logPath.fileSystemRepresentation, O_CREAT | O_WRONLY | O_TRUNC, 0600);
        if (logFD >= 0) {
            dup2(logFD, STDOUT_FILENO);
            dup2(logFD, STDERR_FILENO);
            if (logFD > STDERR_FILENO) close(logFD);
        }
        if (chdir(game.fileSystemRepresentation) != 0)
            return fail(@"Cannot enter the writable game folder.", YES);
        execl(engine.fileSystemRepresentation, engine.fileSystemRepresentation,
              "--noprimaryconf", "--nolocalconf", "--conf", configPath.fileSystemRepresentation, (char *)NULL);
        return fail([NSString stringWithFormat:@"Cannot launch DOSBox: %s", strerror(errno)], YES);
    }
}
