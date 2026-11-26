"""Numerically check the actual viewer projection plus its camera conversion.

Reads viewer source without editing it. Compiles a temporary math-only C++
program against Apple's SIMD; no app, window, emulator or input is started.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise ValueError("Unclosed viewer function")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    parser.add_argument("--source", type=Path, default=root / "NativePreview/Sources/NativePreview.mm")
    parser.add_argument("--shader", type=Path, default=root / "NativePreview/Sources/World.metal")
    parser.add_argument("--report", type=Path, default=Path(__file__).resolve().with_name("metal-contract-verification.json"))
    args = parser.parse_args()
    source, shader = args.source.read_text(), args.shader.read_text()
    # Guard the specific source integration reviewed below. The actual projection
    # function and Projection declaration are extracted verbatim for compilation.
    required = ["float value=[matrix[row*3+col] floatValue]", "rot.columns[col][row]=-value",
                "simd_slerp(simd_quaternion(samples[sampleA].rotation),simd_quaternion(samples[sampleB].rotation),replayAlpha)",
                "rotation.columns[col].x=-rr.columns[col].x",
                "rotation.columns[col].y=rr.columns[col].y",
                "rotation.columns[col].z=rr.columns[col].z",
                "proper.columns[col][row]=-[v floatValue]", "frame.pose={frame.sampleAt,vector3(camera[@\"position\"]),proper,{}}"]
    if any(fragment not in source for fragment in required):
        raise ValueError("Viewer camera integration changed; review before rerunning this source contract check")
    model_shader = "(u.localToWorld * float4(v.position, 1.0)).xyz - u.eye.xyz"
    if model_shader not in shader or "u.relativeWorldToClip * float4(o.relativeWorld, 1.0)" not in shader:
        raise ValueError("Viewer shader camera-relative contract changed")
    declaration = re.search(r"struct Projection\s*\{[^}]+\};", source).group(0)
    pose_declaration = re.search(r"struct Pose\s*\{[^}]+\};", source).group(0)
    projection = function(source, "static float4x4 replayProjection(")
    pose_matrix = function(source, "static float4x4 poseMatrix(")
    harness = r'''
#include <simd/simd.h>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
using simd::float3; using simd::float4; using simd::float4x4;
DECLARATION
PROJECTION
POSE_DECLARATION
POSE_MATRIX
static int checks=0,failed=0; static double worst=0;
static void near(double a,double b,double tolerance=0.00002) {
    checks++; double error=fabs(a-b); worst=std::max(worst,error);
    if(!std::isfinite(error)||error>tolerance)failed++;
}
static simd::float3x3 heading(float units) {
    float a=units*(2*M_PI/2048),c=cosf(a),s=sinf(a);
    // Rc^T for Rick's Ry(-heading), column-major storage.
    return (simd::float3x3){(float3){c,0,-s},(float3){0,1,0},(float3){s,0,c}};
}
int main() {
    Projection p;float farZ=2000000;
    const float aspects[]={4.f/3,16.f/9,21.f/9};
    for(float aspect:aspects) {
        float4x4 actual=replayProjection(p,aspect,farZ);
        float sx=2*p.fx/p.height/aspect,sy=2*p.fy/p.height;
        float ox=(2*p.cx/p.width-1)*(p.width/p.height)/aspect,oy=1-2*p.cy/p.height;
        for(float z:{p.nearZ,1000.f,50000.f,farZ}) for(float x:{-100.f,0.f,100.f}) for(float y:{-50.f,0.f,50.f}) {
            // Independent expected formula in bridge x-right/y-down/z-forward.
            float4 clip=actual*(float4){x,-y,-z,1};
            near(clip.x/clip.w,sx*x/z+ox);
            near(clip.y/clip.w,-sy*y/z+oy);
            near(clip.z/clip.w,farZ/(farZ-p.nearZ)-farZ*p.nearZ/((farZ-p.nearZ)*z));
            near(clip.w,z,.001);
        }
    }
    // Proper Rc^T rotations can be quaternion-interpolated. Bridge -Rc^T has
    // determinant -1 and must not be passed directly to the quaternion constructor.
    for(float h:{0.f,8.f,512.f,1475.f,2040.f}) {
        simd::float3x3 rr=heading(h),bridge,loaded;
        for(int c=0;c<3;c++){bridge.columns[c]=-rr.columns[c];loaded.columns[c]=-bridge.columns[c];}
        near(simd_determinant(bridge),-1);
        near(simd_determinant(loaded),1);
        simd::float3x3 restored=simd_matrix3x3(simd_quaternion(loaded));
        for(int c=0;c<3;c++)for(int r=0;r<3;r++)near(restored.columns[c][r],rr.columns[c][r]);
        simd::float3x3 metal=restored;
        for(int c=0;c<3;c++)metal.columns[c].x=-metal.columns[c].x;
        float3 world={37,-19,400};float3 bv=bridge*world,mv=metal*world;
        near(mv.x,bv.x,.0002);near(mv.y,-bv.y,.0002);near(mv.z,-bv.z,.0002);
    }
    simd::float3x3 midpoint=simd_matrix3x3(simd_slerp(simd_quaternion(heading(2040)),simd_quaternion(heading(8)),.5f));
    for(int c=0;c<3;c++)for(int r=0;r<3;r++)near(midpoint.columns[c][r],c==r ? 1 : 0);
    int cameraChecks=checks;
    // Root-local car rotations have determinant+1. No camera handedness
    // conversion belongs in this model matrix. Verify the actual viewer helper.
    Pose a{1590,{0,0,0},simd_quaternion(heading(0))};
    Pose b{1590,{10,20,30},simd_quaternion(heading(-512))};
    for(float alpha:{0.f,.5f,1.f}) {
        float4x4 model=poseMatrix(a,b,alpha);
        float4 point=model*(float4){1,2,3,1};
        double angle=-M_PI_2*alpha,c=cos(angle),s=sin(angle);
        near(point.x,10*alpha+c+3*s);
        near(point.y,20*alpha+2);
        near(point.z,30*alpha-s+3*c);
        near(point.w,1);
        near(model.columns[3].x,10*alpha);near(model.columns[3].y,20*alpha);near(model.columns[3].z,30*alpha);
        simd::float3x3 r={(float3)model.columns[0].xyz,(float3)model.columns[1].xyz,(float3)model.columns[2].xyz};
        near(simd_determinant(r),1);
    }
    std::cout<<std::setprecision(10)<<"{\"numeric_checks\":"<<checks<<",\"projection_and_camera_checks\":"<<cameraChecks
             <<",\"car_model_checks\":"<<(checks-cameraChecks)<<",\"failures\":"<<failed<<",\"max_absolute_error\":"<<worst<<"}\n";
    return failed ? 1 : 0;
}
'''.replace("POSE_DECLARATION", pose_declaration).replace("POSE_MATRIX", pose_matrix).replace("DECLARATION", declaration).replace("PROJECTION", projection)
    with tempfile.TemporaryDirectory(prefix="rally-metal-contract-") as temporary:
        cpp, binary = Path(temporary) / "contract.cpp", Path(temporary) / "contract"
        cpp.write_text(harness)
        compile_result = subprocess.run(["xcrun", "clang++", "-std=c++17", "-O2", str(cpp), "-o", str(binary)],
                                        capture_output=True, text=True)
        if compile_result.returncode:
            raise RuntimeError(compile_result.stderr)
        completed = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    report = {"result": "passed", "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "shader_sha256": hashlib.sha256(shader.encode()).hexdigest(), **json.loads(completed.stdout),
              "checks": ["Actual viewer replayProjection function compiled verbatim",
                         "Projection matches independent bridge formula at4:3,16:9,21:9 and near/intermediate/far depths",
                         "Bridge determinant-1 matrix converted to proper determinant+1 rotation before quaternion construction",
                         "Final viewer row-X flip equals bridge view-Y/view-Z flip for Metal right-handed view",
                         "Quaternion wrap2040->8 midpoint is identity rather than a full-turn spin",
                         "Actual viewer poseMatrix helper preserves proper car rotation, translation, endpoints and midpoint",
                         "Shader applies root-local-to-world model before subtracting eye once and projecting"],
              "scope": "math-only source contract review; no app/UI/emulator launch; reference main-race projection only"}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
