#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""S1 atomic pose feed, guarded graphics bridge, and normal-keyboard input service.

--diagnostic-read-only never sends input or memory writes. Original physics
remains entirely in DOSBox; this process only reads completed-frame state.
"""
import argparse,base64,hashlib,json,math,os,signal,struct,subprocess,sys,threading,time,urllib.error,uuid
from pathlib import Path
from clock_shared import now_ns
from live_api import LiveAPI,NotReady
from input_lease import InputLease,KeyboardOutput
from profile_s1 import EXE_SHA256,RAM_SIZE,WAIT_LINK,PENDING_LINK,LINKS,executable_profile,resolve
from export_scene import rotation,require,u32
from export_dynamic import actors,part_pose,actor_pointer,actor_slots
import original_draw_distance
from s1_native_client import S1NativeGraphics
from s1_sky import ranges as sky_ranges,sky_state
from native_graphics_policy import GraphicsPolicy,frontend_heartbeat,exact_hud_ready,SUPPORTED_HUD_MODES


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.'+path.name+f'.{os.getpid()}.{threading.get_ident()}.tmp')
    temp.write_bytes(data);os.replace(temp,path)


def publish(path,value):
    atomic(path,(json.dumps(value,separators=(',',':'),allow_nan=False)+'\n').encode())


class Layout:
    def __init__(self,metadata):
        require(metadata['executable_sha256']==EXE_SHA256 and metadata['ram_size']==RAM_SIZE and metadata.get('pointer_bias',0)==0,'Unknown S1 live layout')
        self.metadata=metadata;self.objects=metadata['objects']
        require({o['index'] for o in self.objects}=={1,2,3},'Incomplete S1 mapping')
        for o in self.objects:require(0<=o['physical_base']<=RAM_SIZE-o['virtual_size'],'Invalid mapped extent')
        for field in ('link_base','physical_base'):
            ordered=sorted(self.objects,key=lambda o:o[field])
            require(all(a[field]+a['virtual_size']<=b[field] for a,b in zip(ordered,ordered[1:])),'Overlapping S1 mapping')
    def link(self,va,size=4):
        for o in self.objects:
            delta=va-o['link_base']
            if 0<=delta and size<=o['virtual_size']-delta:return o['physical_base']+delta
        raise ValueError('Unknown S1 link range')
    def to_link(self,physical):
        for o in self.objects:
            if o['physical_base']<=physical<o['physical_base']+o['virtual_size']:return o['link_base']+physical-o['physical_base']
        raise ValueError('Unknown S1 code address')


def camera_pose(raw):
    words=struct.unpack_from('<6i',raw);angles,origin=words[:3],words[3:6]
    require(all(abs(v)<2048*1024 for v in angles),'Invalid original camera angles')
    matrix=rotation(angles)
    return {'position':[origin[i]+128*matrix[i][2] for i in range(3)],'origin':list(origin),'angles':list(angles),
        'rotation':[-matrix[i][k] for k in range(3) for i in range(3)],
        'projection':{'width':640,'height':480,'fx':256.,'fy':307.2,'cx':319.,'cy':312.,'near':128.},
        'projection_source':'S1 active original projected-vertex verification, 59 vertices; original400→480 pixel aspect'}


def coalesce(ranges):
    merged=[]
    for address,size in sorted(ranges):
        require(0<=address<=RAM_SIZE-size,'Pose range outside guest RAM')
        if merged and address<=merged[-1][0]+merged[-1][1]+4096:
            start,length=merged[-1];merged[-1]=(start,max(start+length,address+size)-start)
        else:merged.append((address,size))
    require(len(merged)<=64 and sum(n for _,n in merged)<=2*1024*1024,'Sparse pose budget exceeded')
    return merged


def field(data,address,size):
    for start,raw in data.items():
        if start<=address and address+size<=start+len(raw):return raw[address-start:address-start+size]
    raise ValueError('Atomic response omitted required field')


class Bridge:
    def __init__(self,args):
        self.a=args;self.api=LiveAPI(args.base_url,.3);self.epoch=uuid.uuid4().hex;self.stop=False
        self.layout=None;self.sp=None;self.cached_actors=[];self.model_bases=[];self.scene_key=None;self.assets=None;self.job=None
        self.frame=None;self.frame_error=None;self.last_error=None;self.seq=0;self.pose=None;self.last_clock=None;self.transitions=0;self.first_time=None;self.last_time=None
        self.wait_misses=0;self.last_wait_status=None
        self.lease=InputLease(args.input,self.epoch);self.keyboard=KeyboardOutput(LiveAPI(args.base_url),None,False);self.input_error=None
        if args.diagnostic_read_only:self.keyboard.method='disabled-read-only-diagnostic'
        self.started=time.monotonic();self.actor_info={}
        self.graphics=S1NativeGraphics(LiveAPI(args.base_url,.3));self.graphics_policy=GraphicsPolicy()
        self.graphics_status=None;self.graphics_error=None;self.bootstrap_sent=None
        self.graphics_decision={'ready':False,'phase':'fallback','reason':'Waiting for original S1 layout','renew':True}
        self.exact_hud=None;self.exact_hud_error=None;self.assets_since=0;self.sky_palette=None
        self.generation=0
        self.retry_after=0
        hud=Path(__file__).resolve().parent.parent/'hud-profile.json'
        self.hud=json.loads(hud.read_text()) if hud.is_file() else None

    def invalidate_scene(self,reason):
        self.generation+=1
        if self.job:
            process,log,*_=self.job
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
            log.close();self.job=None
        self.cached_actors=[];self.model_bases=[];self.scene_key=None;self.assets=None;self.pose=None
        self.exact_hud=None;self.assets_since=now_ns();self.sky_palette=None
        self.last_error=reason

    def guard_actor(self,actor,current,model_pointer,model_id):
        if actor_pointer(current)!=actor['guest_address'] or model_pointer!=self.model_bases[actor['model']] or model_id!=actor['model']:
            self.invalidate_scene('Actor roster/model replaced; rebuilding guarded original meshes')
            raise NotReady('Actor roster/model replaced; rebuilding guarded original meshes')

    def guard_roster(self,table):
        try:current=[(index,pointer)for index,_,pointer in actor_slots(table)]
        except ValueError as error:
            self.invalidate_scene('Original actor list changed')
            raise NotReady('Original actor list changed')from error
        if current!=[(actor['list_index'],actor['guest_address'])for actor in self.cached_actors]:
            self.invalidate_scene('Original actor roster changed')
            raise NotReady('Original actor roster changed')

    def parent_alive(self):
        if not self.a.parent_pid:return True
        try:os.kill(self.a.parent_pid,0);return True
        except ProcessLookupError:return False

    def record_wait(self,error):
        # A busy guest or scene transition is an expected polling outcome.
        # Preserve genuine errors until a completed, validated read succeeds.
        self.wait_misses+=1;self.last_wait_status=str(error)

    def input_worker(self):
        while not self.stop:
            try:self.keyboard.send(self.lease.desired());self.input_error=None
            except (OSError,ValueError) as e:self.input_error=str(e)
            time.sleep(.02)
        try:self.keyboard.send(set(),force=True)
        except (OSError,ValueError):pass

    def graphics_worker(self):
        # Separate from pose polling/export so a stalled producer cannot keep
        # renewing the engine renderer lease. A dead frontend also expires.
        retry=0.
        while not self.stop:
            try:
                if self.layout and not self.graphics.installed and time.monotonic()>=retry:
                    executable_profile((self.a.game_root/'STARTH.EXE').read_bytes())
                    self.graphics_status=self.graphics.control(False,self.layout.objects)
                now=now_ns();assets=self.assets
                front=frontend_heartbeat(self.a.input,self.epoch,assets.get('epoch') if assets else None,now)
                decision=self.graphics_policy.decide(now=now,pose=self.pose,assets=assets,
                    assets_since=self.assets_since,hud=self.exact_hud,frontend=front,stopped=self.stop)
                self.graphics_decision=decision
                if self.graphics.installed:
                    # Bootstrap sends a single 600ms lease. Once exact HUD and
                    # actual native rendering are confirmed, renew normally.
                    if decision['phase']=='bootstrap' and self.bootstrap_sent!=decision['bootstrap_id']:
                        self.graphics_status=self.graphics.control(True);self.bootstrap_sent=decision['bootstrap_id']
                    elif decision['phase']!='bootstrap':
                        result=self.graphics.heartbeat(decision['ready'])
                        if result is not None:self.graphics_status=result
                self.graphics_error=None
            except (OSError,ValueError,KeyError,TypeError) as e:
                self.graphics_error=str(e);retry=time.monotonic()+1
                self.graphics_decision={'ready':False,'phase':'fallback','reason':str(e),'renew':True}
                try:
                    if self.graphics.installed:self.graphics.control(False)
                except (OSError,ValueError,KeyError):pass
            time.sleep(.02)
        try:
            if self.graphics.installed:self.graphics.control(False)
        except (OSError,ValueError,KeyError):pass

    def frame_worker(self):
        api=LiveAPI(self.a.base_url,.4)
        hud_api=S1NativeGraphics(LiveAPI(self.a.base_url,.3))
        while not self.stop:
            before=time.monotonic()
            try:
                raw,meta=api.frame()
                if self.frame is None or meta['sequence']!=self.frame['sequence']:
                    path=self.a.state.parent/'frames'/f"frame-{meta['sequence']%4}.bgra";atomic(path,raw)
                    self.frame=dict(meta,path=str(path));self.frame_error=None
            except (OSError,ValueError,KeyError) as e:self.frame_error=str(e)
            if not self.a.diagnostic_read_only and self.assets:
                epoch=self.assets['epoch']
                try:
                    raw,meta=hud_api.hud()
                    if (self.assets and self.assets['epoch']==epoch and meta['capture_ns']>=self.assets_since
                            and (not self.exact_hud or meta['sequence']!=self.exact_hud['sequence'])):
                        path=self.a.state.parent/'frames'/f"hud-{meta['sequence']%4}.bgra";atomic(path,raw)
                        self.exact_hud=dict(meta,path=str(path),assets_epoch=epoch);self.exact_hud_error=None
                except (OSError,ValueError,KeyError) as e:self.exact_hud_error=str(e)
            time.sleep(max(.002,1/30-(time.monotonic()-before)))

    def load_layout(self):
        if self.layout or not self.a.layout.is_file():return
        self.layout=Layout(json.loads(self.a.layout.read_text()))
        self.address={k:self.layout.link(v) for k,v in LINKS.items()};self.helper=self.layout.link(WAIT_LINK)

    def capture_assets(self,key):
        data,info=self.api.batch([(0,RAM_SIZE)],self.helper,full=True);ram=data[0]
        objects,fixups,_,_=executable_profile((self.a.game_root/'STARTH.EXE').read_bytes());loaded,_,_,physical=resolve(ram,objects,fixups)
        require(loaded==self.layout.objects,'S1 live mapping changed')
        model_bases,roots=actors(ram,physical)
        name=ram[physical(LINKS['world_name']):physical(LINKS['world_name'])+16].split(b'\0')[0].decode('ascii').upper()
        actual=(name,u32(ram,physical(LINKS['rows'])),u32(ram,physical(LINKS['models'])),u32(ram,physical(LINKS['materials'])))
        if actual!=key:raise NotReady('Scene changed during asset capture')
        track=int(name[-1]);world=self.a.scenes_root/f'track{track}/scene.json';require(world.is_file(),'Original offline scene has not been exported')
        folder=self.a.cache_root/(hashlib.sha256(repr(key).encode()).hexdigest()[:12]+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
        (folder/'ram.bin').write_bytes(ram)
        meta=dict(self.layout.metadata,ram_sha256=hashlib.sha256(ram).hexdigest(),objects=loaded)
        (folder/'snapshot.json').write_text(json.dumps(meta,indent=2)+'\n')
        log=(folder/'export.log').open('wb')
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('export_dynamic.py')),'--ram',str(folder/'ram.bin'),'--metadata',str(folder/'snapshot.json'),
            '--game-root',str(self.a.game_root),'--output',str(folder/'Dynamic'),'--world-scene',str(world)],stdout=log,stderr=subprocess.STDOUT,
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
        self.generation+=1
        self.job=(process,log,folder,key,world,self.generation);self.cached_actors=roots;self.model_bases=model_bases;self.scene_key=key;self.assets=None

    def poll_job(self):
        if not self.job or self.job[0].poll() is None:return
        process,log,folder,key,world,generation=self.job;log.close();self.job=None
        if generation!=self.generation or key!=self.scene_key:return
        if process.returncode!=0:
            self.invalidate_scene('Original dynamic-part export failed; see export.log')
            self.retry_after=time.monotonic()+2
            raise NotReady('Original dynamic-part export failed; retrying guarded capture')
        sky_dir=folder/'Dynamic/sky';sky=json.loads((sky_dir/'sky.json').read_text())
        require(sky.get('schema')=='screamer1-sky/v1' and sky.get('track')==int(key[0][-1]),'Original S1 sky descriptor differs')
        require((sky_dir/'texture.png').is_file(),'Original S1 sky texture missing')
        self.sky_palette=sky['palette_rgb']
        self.assets={'world_scene':str(world),'cars_scene':str(folder/'Dynamic/scene.json'),'epoch':folder.name,
                     'sky_texture':str(sky_dir/'texture.png')}
        runtime=Path(__file__).resolve().parent.parent
        conditions_root=runtime if (runtime/'Conditions').is_dir() else Path(__file__).resolve().parents[4]
        sys.path.insert(0,str(conditions_root)) if str(conditions_root) not in sys.path else None
        from Conditions.s1 import build_variants
        self.assets['condition_variants']=build_variants(self.a.game_root,int(key[0][-1]),folder/'Conditions',
                                                        world,folder/'Dynamic/scene.json')
        self.assets_since=now_ns();self.exact_hud=None

    def read_pose(self):
        a=self.address
        ranges=[(self.helper,11),(a['pending'],4),(a['smoothed_dt'],24),(a['world_name'],16),(a['rows'],4),(a['models'],4),(a['materials'],4),
            (a['main_camera'],112),(self.layout.link(0x8a7c0),0x40),(self.layout.link(0x1100c0),4),(a['scene_list'],512*4)]
        ranges+=sky_ranges(self.layout)
        ranges+=original_draw_distance.ranges(self.layout,'screamer')
        if self.model_bases:
            ranges.append((self.scene_key[2],len(self.model_bases)*4))
        if self.sp is not None:ranges.append((self.sp+24,4))
        ranges += [(v['guest_address'],0x40+v['parts']*0x20) for v in self.cached_actors]
        before=now_ns();data,info=self.api.batch(coalesce(ranges),self.helper);after=now_ns()
        code=field(data,self.helper,11)
        require(code[:2]==b'\x8b\x15' and u32(code,2)==a['pending'] and code[6:]==bytes.fromhex('83fa0272f5'),'Original S1 wait guard failed')
        actual_sp=info['linear_esp']
        if actual_sp!=self.sp:self.sp=actual_sp;raise NotReady('Refreshing wait stack address')
        caller=self.layout.to_link(u32(field(data,self.sp+24,4),0))
        phase='attract' if caller==0x27747 else 'race' if caller==0x1ff4f else 'menu' if caller==0x2aa96 else 'loading'
        name=field(data,a['world_name'],16).split(b'\0')[0].decode('ascii','replace').upper()
        require(name in {f'MAP{i}' for i in range(1,7)} or phase not in {'race','attract'},'Unknown original track name')
        key=(name,*(u32(field(data,a[k],4),0) for k in ('rows','models','materials')))
        clocks=field(data,a['smoothed_dt'],24);dt,raw_dt=struct.unpack_from('<2f',clocks);elapsed=struct.unpack_from('<f',clocks,12)[0]
        require(all(math.isfinite(v) for v in (dt,raw_dt,elapsed)),'Nonfinite original clocks')
        value={'status':phase,'sample_monotonic_ns':(before+after)//2,'acquisition_ms':(after-before)/1e6,'caller_link':caller,
            'track_id':int(name[-1]) if name.startswith('MAP') else None,'world_name':name,'scene_key':key,
            'clock_bits':clocks[12:16].hex(),'elapsed':elapsed,'smoothed_dt':dt,'raw_dt':raw_dt,'instances':[],'camera':None}
        value['original_draw_distance']=original_draw_distance.distance(self.layout,data,'screamer')
        value['original_hud_mode']=u32(field(data,self.layout.link(0x1100c0),4),0)
        value['sky']=sky_state(self.layout,lambda address,size:field(data,address,size),self.sky_palette,phase)
        if phase not in {'race','attract'}:return value
        if key!=self.scene_key:
            if time.monotonic()<self.retry_after:raise NotReady('Waiting to retry original scene capture')
            self.invalidate_scene('Loading original scene assets')
            self.capture_assets(key);return value
        cam=camera_pose(field(data,a['main_camera'],112))
        cy=u32(field(data,self.layout.link(0x8a7c0),0x40),0x1c)
        require(0<cy<480,'Unknown original vertical projection center')
        cam['projection']['cy']=cy*1.2
        value['camera']=original_draw_distance.attach_camera(cam,value['original_draw_distance'])
        table=field(data,a['scene_list'],512*4)
        self.guard_roster(table)
        for actor in self.cached_actors:
            current=u32(table,4*actor['list_index'])
            model_pointer=u32(field(data,key[2],len(self.model_bases)*4),4*actor['model'])
            raw=field(data,actor['guest_address'],0x40+actor['parts']*0x20)
            self.guard_actor(actor,current,model_pointer,u32(raw,0))
            if current&0x40000000:continue
            updated=dict(actor,position=list(struct.unpack_from('<3i',raw,8)),angles=list(struct.unpack_from('<3i',raw,0x14)))
            # Rebase the immutable byte window so part_pose never dereferences
            # an external host pointer or uncaptured guest memory.
            updated['guest_address']=0
            for slot in range(actor['parts']):value['instances'].append(part_pose(raw,updated,slot))
        return value

    def state(self):
        pose=self.pose or {};now=now_ns();age=(now-pose.get('sample_monotonic_ns',now))/1e9
        ready=bool(self.assets and pose.get('camera') and pose.get('status') in {'race','attract'} and age<.15)
        exact=exact_hud_ready(self.exact_hud,pose.get('original_hud_mode'),
            self.assets.get('epoch') if self.assets else None,self.assets_since,now)
        hud={'complete':False,'primary_hud_validated':False,'rects':[],'layers':[],
             'missing':['Waiting for exact original HUD byte-write coverage.']}
        if exact:
            h=self.exact_hud
            hud={'complete':True,'primary_hud_validated':True,'source_width':640,'source_height':480,
                'pixel_aspect_already_applied':True,'rects':[],
                'layers':[{'path':h['path'],'format':'bgra8','premultiplied':True,'x':0,'y':0,'width':640,'height':480,
                           'stride':2560,'anchor':'center','sequence':h['sequence']}],
                'sequence':h['sequence'],'capture_ns':h['capture_ns'],'coverage':h['coverage'],
                'validation_scope':'Exact original main HUD and post-HUD framebuffer byte writes, including same-value stores.',
                'missing':[]}
        supported=pose.get('original_hud_mode') in SUPPORTED_HUD_MODES
        native_mode=pose['status'] if ready and pose.get('status')=='race' and supported and self.graphics.installed else 'framebuffer'
        if self.a.diagnostic_read_only and ready and pose.get('status')=='attract':native_mode='attract'
        notice=None
        if pose.get('status')=='race':
            if not supported:notice='Use F1, F3 or F4 for the high-resolution race view.'
            elif not exact:notice='Preparing the original dashboard for Metal.'
        decision=self.graphics_decision
        return {'schema':'screamer-live/v1','epoch':self.epoch,'sequence':self.seq,'seq':self.seq,'running':not self.stop,
            # Original 83843/838F7/83BB7 reject backfaces. Exported visible
            # polygon winding is clockwise under the native camera projection.
            'cull_back_faces':True,
            'published_monotonic_ns':now,'sample_monotonic_ns':pose.get('sample_monotonic_ns',now),'physics_period_ms':20,
            'status':pose.get('status','loading'),'mode':native_mode,'is_attract':pose.get('status')=='attract',
            'mode_detection':'Original intro caller27747; main-race caller1ff4f; menu caller2aa96. AI autoplay inside main race not separately identified.',
            'original_draw_distance':pose.get('original_draw_distance'),'camera':pose.get('camera'),'sky':pose.get('sky',{'kind':'s1','enabled':False,'ground_rgb':[0,0,0],'flat_rgb':[0,0,0],'center_y':260,'view_last_y':400}),'instances':pose.get('instances',[]),'assets':self.assets if ready else None,
            'assets_ready':ready,'pose_age_ms':age*1000,'framebuffer':self.frame,'hud':hud,'original_hud_mode':pose.get('original_hud_mode'),'renderer_notice':notice,
            'track_id':pose.get('track_id'),'world_name':pose.get('world_name'),'real_clock':pose.get('elapsed'),'simulation_clock':pose.get('elapsed'),
            'consistency':'atomic-cpu-step-at-original-two-tick-frame-wait','pose_sequence':self.transitions,
            'original_smoothed_dt':pose.get('smoothed_dt'),'original_raw_dt':pose.get('raw_dt'),
            'native_graphics':{'phase':decision['phase'],'renderer_ready':decision['ready'],'reason':decision['reason'],
                'engine':self.graphics_status,'error':self.graphics_error,'hud_error':self.exact_hud_error},
            'input':{'method':self.keyboard.method,'focused':self.lease.focused,'held_keys':sorted(self.keyboard.held),'error':self.input_error},
            'metrics':{'distinct_physics_clock_states':self.transitions,'observed_clock_hz':(self.transitions-1)/((self.last_time-self.first_time)/1e9) if self.transitions>1 else 0,
                'completed_frame_wait_misses':self.wait_misses},
            'last_wait_status':self.last_wait_status,
            'error':self.last_error,'limitations':['Native gameplay currently supports original digital HUD mode2; other views retain the original framebuffer. Original sky assets and atomic sky state are published for native composition.',
                'E0 fades reconstruct original SMG ramps before palette quantization; unsupported C0 is counted explicitly. Native camera verified against original projected vertices.',
                'Mode guard identifies original scene frame but does not yet distinguish player race from automatic intro/demo.']}

    def run(self):
        self.a.state.parent.mkdir(parents=True,exist_ok=True);self.a.cache_root.mkdir(parents=True,exist_ok=True)
        frame=threading.Thread(target=self.frame_worker,daemon=True);frame.start()
        graphics=None
        if not self.a.diagnostic_read_only:
            graphics=threading.Thread(target=self.graphics_worker,daemon=True);graphics.start()
        inp=None
        if not self.a.diagnostic_read_only:inp=threading.Thread(target=self.input_worker,daemon=True);inp.start()
        def stopping(*_):self.stop=True
        signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
        try:
            while not self.stop and self.parent_alive() and (not self.a.seconds or time.monotonic()-self.started<self.a.seconds):
                before=time.monotonic()
                try:
                    self.load_layout();self.poll_job()
                    if self.layout:
                        pose=self.read_pose()
                        changed=pose['clock_bits']!=self.last_clock
                        if changed:
                            self.last_clock=pose['clock_bits'];self.transitions+=1
                            self.last_time=pose['sample_monotonic_ns']
                            if self.first_time is None:self.first_time=self.last_time
                        if changed or self.pose is None or pose['status']!=self.pose['status'] or pose['scene_key']!=self.pose['scene_key']:
                            self.pose=pose
                        self.last_error=None;self.last_wait_status=None
                except NotReady as e:
                    self.record_wait(e)
                except (OSError,ValueError,KeyError,struct.error) as e:
                    self.last_error=str(e)
                    if isinstance(e,(ValueError,KeyError,struct.error)) and self.layout:
                        self.invalidate_scene(str(e))
                self.seq+=1;publish(self.a.state,self.state());time.sleep(max(.001,.01-(time.monotonic()-before)))
        finally:
            self.stop=True
            if inp:inp.join(timeout=2)
            if graphics:graphics.join(timeout=2)
            frame.join(timeout=2)
            if self.job:
                self.job[0].terminate()
                try:self.job[0].wait(timeout=3)
                except subprocess.TimeoutExpired:self.job[0].kill();self.job[0].wait()
                self.job[1].close()
            publish(self.a.state,self.state())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',required=True)
    for name in ('layout','state','input','game-root','scenes-root','cache-root'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--parent-pid',type=int);p.add_argument('--seconds',type=float,default=0);p.add_argument('--diagnostic-read-only',action='store_true')
    a=p.parse_args();Bridge(a).run()


if __name__=='__main__':main()
