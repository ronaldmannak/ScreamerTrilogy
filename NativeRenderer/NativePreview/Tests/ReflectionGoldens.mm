#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <CommonCrypto/CommonDigest.h>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <vector>
struct Input { float position[3],normal[3],scroll[2]; };
static_assert(sizeof(Input)==32);
static NSString* sha(NSData* data){unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256(data.bytes,(CC_LONG)data.length,digest);NSMutableString*s=[NSMutableString string];for(auto x:digest)[s appendFormat:@"%02x",x];return s;}
int main(int argc,const char**argv){@autoreleasepool{try{
 if(argc!=4)throw std::runtime_error("Usage: validate_reflection_goldens World.metal direct-UV-proof.json report.json");
 NSString* shaderPath=[NSString stringWithUTF8String:argv[1]];NSData* shaderBytes=[NSData dataWithContentsOfFile:shaderPath];NSString*shader=[[NSString alloc]initWithData:shaderBytes encoding:NSUTF8StringEncoding];
 if(![shader containsString:@"originalS1ReflectionUV("])throw std::runtime_error("Production texgen helper missing");
 shader=[shader stringByAppendingString:@"\nstruct GoldenInput { packed_float3 position; packed_float3 normal; packed_float2 scroll; };\nkernel void probeOriginalReflection(device const GoldenInput *inputs [[buffer(0)]], device float2 *outputs [[buffer(1)]], uint id [[thread_position_in_grid]]) { GoldenInput v=inputs[id]; outputs[id]=originalS1ReflectionUV(float3(v.position),float3(v.normal),float2(v.scroll)); }\n"];
 NSData* proofBytes=[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]];NSDictionary* proof=[NSJSONSerialization JSONObjectWithData:proofBytes options:0 error:nil];NSArray*rows=proof[@"rows"],*scroll=proof[@"original_scroll"];
 if(![rows isKindOfClass:NSArray.class]||rows.count!=87||scroll.count!=2)throw std::runtime_error("Expected87 original C3E84 golden vertices");
 std::vector<Input> inputs(rows.count);
 for(NSUInteger i=0;i<rows.count;i++){NSDictionary*r=rows[i];for(int c=0;c<3;c++){inputs[i].position[c]=[r[@"source_position"][c]floatValue];inputs[i].normal[c]=[r[@"source_normal"][c]floatValue];}for(int c=0;c<2;c++)inputs[i].scroll[c]=[scroll[c]floatValue]/256.f;}
 id<MTLDevice>device=MTLCreateSystemDefaultDevice();if(!device)throw std::runtime_error("No Metal device");NSError*error=nil;
 id<MTLLibrary>library=[device newLibraryWithSource:shader options:nil error:&error];if(!library)throw std::runtime_error(error.localizedDescription.UTF8String);
 id<MTLComputePipelineState>pipeline=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"probeOriginalReflection"] error:&error];if(!pipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
 id<MTLBuffer>input=[device newBufferWithBytes:inputs.data() length:inputs.size()*sizeof(Input) options:MTLResourceStorageModeShared];id<MTLBuffer>output=[device newBufferWithLength:rows.count*2*sizeof(float) options:MTLResourceStorageModeShared];
 id<MTLCommandQueue>queue=[device newCommandQueue];id<MTLCommandBuffer>cb=[queue commandBuffer];id<MTLComputeCommandEncoder>encoder=[cb computeCommandEncoder];[encoder setComputePipelineState:pipeline];[encoder setBuffer:input offset:0 atIndex:0];[encoder setBuffer:output offset:0 atIndex:1];[encoder dispatchThreads:MTLSizeMake(rows.count,1,1) threadsPerThreadgroup:MTLSizeMake(32,1,1)];[encoder endEncoding];[cb commit];[cb waitUntilCompleted];if(cb.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(cb.error.localizedDescription.UTF8String);
 const float*actual=static_cast<const float*>(output.contents);NSMutableArray*failures=[NSMutableArray array],*checks=[NSMutableArray array];double maximum=0;NSUInteger negatives=0;
 for(NSUInteger i=0;i<rows.count;i++){NSDictionary*r=rows[i];NSArray*expected=r[@"original_uv"];double delta=0;for(int c=0;c<2;c++){delta=fmax(delta,fabs(actual[i*2+c]-[expected[c]doubleValue]/256.));if(actual[i*2+c]<0)negatives++;}maximum=fmax(maximum,delta);
  NSDictionary*check=@{@"vertex":r[@"vertex"],@"expected_source_UV":expected,@"actual_GPU_UV":@[@(actual[i*2]*256),@(actual[i*2+1]*256)],@"maximum_normalized_error":@(delta)};[checks addObject:check];if(delta>1e-6)[failures addObject:check];
 }
 NSDictionary*report=@{@"device":device.name,@"production_shader":shaderPath,@"production_shader_sha256":sha(shaderBytes),@"source_proof":@(argv[2]),@"source_proof_sha256":sha(proofBytes),@"actual_production_function":@"originalS1ReflectionUV called by worldVertex and appended probe kernel",@"formula_duplicated_in_test_shader":@NO,@"original_cases":@(rows.count),@"matches":@(rows.count-failures.count),@"negative_GPU_components_preserved":@(negatives),@"maximum_normalized_error":@(maximum),@"failures":failures,@"checks":checks,@"game_inputs":@NO,@"game_execution":@NO,@"scope":@"Validates actual production texgen helper against saved original C3E84 outputs; runtime camera/part basis and texture sampling are separate checks."};
 NSData*json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];if(![json writeToFile:[NSString stringWithUTF8String:argv[3]] atomically:YES])throw std::runtime_error("Cannot write report");
 printf("Original C3E84 GPU goldens: %lu/%lu; max normalized error %.9g; negative components %lu\n",(unsigned long)(rows.count-failures.count),(unsigned long)rows.count,maximum,(unsigned long)negatives);return failures.count?2:0;
 }catch(const std::exception&e){fprintf(stderr,"%s\n",e.what());return 1;}}}
