// Native Metal preview renderer. Game data is supplied separately from owned assets.
#include <metal_stdlib>
using namespace metal;
struct VertexIn {
    float3 position [[attribute(0)]];
    float2 uv [[attribute(1)]];
    float4 color [[attribute(2)]];
    float3 normal [[attribute(3)]];
};
// Must match ConditionsUniforms in Conditions.inc. These are presentation-only.
struct ConditionsUniforms {
    float4 weights; // night haze, grey fog, fog start distance, inverse fog span
    float4 fogColor;
    float4 nightFog;
};
struct Uniforms {
    float4x4 relativeWorldToClip;
    float4 eye;
    float4 options; // textured, alpha threshold, original blend equation, S1 A0 reflection
    float4x4 localToWorld;
    float4x4 reflectionWorldToView;
    float4 reflectionScroll;
    ConditionsUniforms conditions;
};
struct VertexOut {
    float4 position [[position]];
    float2 uv;
    float4 color;
    float3 relativeWorld;
};
// Original S1 C2270/C24E0 and DBB raster path. Preserve signed UVs
// through interpolation; the repeating sampler wraps only at texture access.
float2 originalS1ReflectionUV(float3 view, float3 normal, float2 scroll) {
    float3 incident = view * rsqrt(max(dot(view, view), 1.0e-20));
    float3 reflected = 2.0 * dot(normal, incident) * normal - incident;
    // FNINIT + FIST rounds nearest with ties-to-even; source normals stay unnormalized.
    return (127.0 + rint(127.0 * reflected.xz)) / 256.0 - scroll;
}
vertex VertexOut worldVertex(VertexIn v [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    VertexOut o;
    o.relativeWorld = (u.localToWorld * float4(v.position, 1.0)).xyz - u.eye.xyz;
    o.position = u.relativeWorldToClip * float4(o.relativeWorld, 1.0);
    o.uv = v.uv;
    o.color = v.color;
    if (u.options.w > 0.5) {
        float3 world = (u.localToWorld * float4(v.position, 1.0)).xyz;
        float3 view = (u.reflectionWorldToView * float4(world, 1.0)).xyz;
        float3 n = (u.reflectionWorldToView * u.localToWorld * float4(v.normal, 0.0)).xyz;
        o.uv = originalS1ReflectionUV(view, n, u.reflectionScroll.xy);
    }
    return o;
}
// Night artwork is selected from the owned original texture/model banks.
// Preserve its colors; the original 3dfx night mode only adds black distance haze.
float3 conditionsWorldRGB(float3 color, float distance, constant ConditionsUniforms &conditions) {
    float night=saturate(conditions.weights.x),fog=saturate(conditions.weights.y);
    if(night<=0 && fog<=0)return color; // Preserve the original Day result exactly.
    if(night>0){
        float span=saturate((distance-conditions.nightFog.x)*conditions.nightFog.y);
        color*=1-span*span*(3-2*span)*night;
    }
    if(fog>0){
        float span=saturate((distance-conditions.weights.z)*conditions.weights.w);
        float amount=span*span*(3-2*span)*fog;
        color=mix(color,conditions.fogColor.rgb,amount);
    }
    return color;
}
float3 conditionsSkyRGB(float3 color, constant ConditionsUniforms &conditions) {
    float fog=saturate(conditions.weights.y);
    // The distant background meets the world fog colour without a visible seam.
    if(fog>0)color=mix(color,conditions.fogColor.rgb,fog);
    return color;
}
fragment float4 worldFragment(VertexOut v [[stage_in]], constant Uniforms &u [[buffer(1)]],
                              texture2d<float> tex [[texture(0)]], sampler sampling [[sampler(0)]]) {
    float4 color = v.color;
    if (u.options.x > 0.5) color *= tex.sample(sampling, v.uv);
    if (color.a < u.options.y) discard_fragment();
    // Original textures contain authored shading. Opaque and keyed world
    // materials both write an opaque result after the key test.
    float distance=length(v.relativeWorld);
    // Original mode 7 grey light cones use 2*source*destination and disable fog.
    float3 rgb=abs(u.options.z-2.0)<0.1?color.rgb:conditionsWorldRGB(color.rgb,distance,u.conditions);
    return float4(rgb, u.options.z > 0.5 ? color.a : 1.0);
}
struct FramebufferOut { float4 position [[position]]; float2 uv; };
struct FramebufferUniforms { float4 destination;float4 source; };
vertex FramebufferOut framebufferVertex(uint id [[vertex_id]],constant FramebufferUniforms &u [[buffer(0)]]) {
    const float2 positions[6]={float2(-1,-1),float2(1,-1),float2(-1,1),float2(-1,1),float2(1,-1),float2(1,1)};
    FramebufferOut result;result.position=float4(u.destination.xy+positions[id]*u.destination.zw,0,1);
    result.uv=u.source.xy+float2((positions[id].x+1)*.5,(1-positions[id].y)*.5)*u.source.zw;return result;
}
fragment float4 framebufferFragment(FramebufferOut v [[stage_in]],texture2d<float> tex [[texture(0)]],sampler sampling [[sampler(0)]]) {
    return float4(tex.sample(sampling,v.uv).rgb,1);
}
fragment float4 overlayFragment(FramebufferOut v [[stage_in]],texture2d<float> tex [[texture(0)]],sampler sampling [[sampler(0)]]) {
    return tex.sample(sampling,v.uv);
}
fragment float4 backgroundFragment(FramebufferOut v [[stage_in]],constant float4 &color [[buffer(0)]],constant Uniforms &u [[buffer(1)]],texture2d<float> tex [[texture(0)]],sampler sampling [[sampler(0)]]) {
    float4 result=color.a>=0 ? color : float4(tex.sample(sampling,v.uv).rgb,1);
    return float4(conditionsSkyRGB(result.rgb,u.conditions),result.a);
}
