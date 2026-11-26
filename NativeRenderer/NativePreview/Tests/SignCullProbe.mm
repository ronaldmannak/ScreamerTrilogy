#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE to the production NativePreview.mm path
#endif
#define main includedProductionMain
#include PREVIEW_SOURCE_FILE
#undef main
#include <fstream>
int main(int argc,const char **argv){@autoreleasepool{try{
 if(argc!=3)throw std::runtime_error("usage SignProbe fixture outputDirectory");
 NSString *fixture=[NSString stringWithUTF8String:argv[1]],*out=[NSString stringWithUTF8String:argv[2]];
 [[NSFileManager defaultManager]createDirectoryAtPath:out withIntermediateDirectories:YES attributes:nil error:nil];
 NSString *shader=[[@(PREVIEW_SOURCE_FILE) stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"World.metal"];
 NSMutableArray *results=[NSMutableArray array];
 for(NSString *mesh in @[@"both",@"face-a",@"face-b"]){
  PreviewRenderer *renderer=[[PreviewRenderer alloc]initWithScene:[fixture stringByAppendingPathComponent:[mesh stringByAppendingPathComponent:@"scene.json"]] shader:shader replay:[fixture stringByAppendingPathComponent:@"replay.json"] cars:nil report:nil];
  auto &s=*renderer->state;s.widescreen=false;s.extendedDistance=true;
  MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:640 height:480 mipmapped:NO];d.storageMode=MTLStorageModeShared;d.usage=MTLTextureUsageRenderTarget;
  id<MTLTexture> target=[s.device newTextureWithDescriptor:d];
  for(int pose=0;pose<18;pose++)for(int cull=0;cull<2;cull++){
   s.fixedTime=pose;s.cullBackFaces=cull;
   id<MTLCommandBuffer> cb=[renderer encodeTo:target drawable:nil];[cb waitUntilCompleted];if(cb.status==MTLCommandBufferStatusError)throw std::runtime_error(cb.error.localizedDescription.UTF8String);
   NSString *name=[NSString stringWithFormat:@"%@-%02d-%@",mesh,pose,cull?@"back":@"none"];
   std::vector<unsigned char> bytes(640*480*4);[target getBytes:bytes.data() bytesPerRow:640*4 fromRegion:MTLRegionMake2D(0,0,640,480) mipmapLevel:0];
   [[NSData dataWithBytes:bytes.data() length:bytes.size()]writeToFile:[out stringByAppendingPathComponent:[name stringByAppendingPathExtension:@"bgra"]] atomically:NO];
   if(pose==0||pose==9)savePNG(target,[out stringByAppendingPathComponent:[name stringByAppendingPathExtension:@"png"]]);
   [results addObject:@{@"name":name,@"cull_back_faces":@(s.cullBackFaces),@"triangles":@(s.triangles)}];
  }
 }
 [NSJSONSerialization dataWithJSONObject:results options:NSJSONWritingPrettyPrinted error:nil];
 [[NSJSONSerialization dataWithJSONObject:results options:NSJSONWritingPrettyPrinted error:nil] writeToFile:[out stringByAppendingPathComponent:@"render-proof.json"]atomically:NO];
 return 0;
}catch(const std::exception&e){fprintf(stderr,"SignProbe: %s\n",e.what());return 1;}}}
