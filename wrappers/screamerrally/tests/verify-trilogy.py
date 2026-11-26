#!/usr/bin/env python3
"""Verify launch modes, expected DOS binary hashes, migration, and save preservation."""
from pathlib import Path
import argparse, hashlib, json, subprocess, tempfile

TITLES={'screamer':'Screamer','screamer2':'Screamer 2','screamerrally':'Screamer Rally'}
RALLY_HASHES={
 (False,0):'ff46ee5f74bf2b228a7a462cb25c50a228ec705d30e69b2b291887db036e1c98',
 (False,1):'da8d6783f8b3f3fffef3f4ceab2499fc09d8d982b64f19f56f5dee3108ed8489',
 (False,2):'86a8d28d9c18e3e14f820ae6c3be8c3813941183f62fb3e39eba8e8adb28c601',
 (True,0):'7e927361e8858ab98eb8b00d476356cb892ea654b684a5d63ef1df15c881b9c9',
 (True,1):'d23f04872febee9dabfe47fe061f6058311006b057177190542507dbbb0994dd',
 (True,2):'31a426c491a7ffb98af6950fde620833761ecd1447fc9fa15ceca3c32862a520'}
S2_HASHES={(False,0):'05f576866f26602be303343c5e9104132616f464b71ed6ae958e99a668e5c7c8',
 (False,1):'b53e735c3b38cca7697c0a95368ddb5b87fd8aee40a183a5c17d89460766b393',
 (True,0):'15e36109931525a2895af814488c402b5394e03eec3ae8896c922adbd885abdc',
 (True,1):'887921864b27bf57835e5175895037a5a6d0609207f790d85b265088d5b6663b'}
S1_HASHES={(False,0):'1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3',
 (False,1):'4d77cb6e77a0989bac4edb892c897285b16969ecb4f31f529ecc59408f1d635b',
 (True,0):'04d2adc73e5d1ccbb2aadc9978c7b5dcded33114e888181e3206d2e0a25a5541',
 (True,1):'c68f02bd183c1254833099d00a5a9e5ae8ee4f37cc47a3f4cd9c531b2332437c'}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def verify(key, app):
 resource=app/'Contents/Resources';profile=json.loads((resource/'game-profile.json').read_text());m=profile['enhancements']
 hashes={'screamer':S1_HASHES,'screamer2':S2_HASHES,'screamerrally':RALLY_HASHES}[key]
 executable=app/'Contents/MacOS/GameLauncher';source=resource/'game'/profile['program']
 assert sha(source)==m['sha256']
 assert sha(resource/'SelectionBackground.png')==sha(app/'Contents/Helpers/Game Options.app/Contents/Resources/SelectionBackground.png')
 checks=[]
 with tempfile.TemporaryDirectory(prefix=f'{key}-modes-') as temporary:
  data=Path(temporary)/'save folder with spaces';game=data/'Game';game_directory=game/Path(profile['program']).parent
  def prepare(wide, level, expected_exit=0):
   command=[str(executable),'--prepare-only','--data-dir',str(data),'--widescreen' if wide else '--original-aspect', '--distance-level',str(level)]
   result=subprocess.run(command,text=True,capture_output=True,timeout=12)
   assert result.returncode==expected_exit,result.stdout+result.stderr
   return result
  prepare(False,0)
  sentinel=game_directory/'PRESERVE.SAV';sentinel.write_bytes(b'Existing save sentinel\0\xff')
  tracked=[sentinel,game/profile['program'],game_directory/'SCREAMER.CFG']
  for controls in [game_directory/'CONFIG/CONTROLS.CFG',game_directory/'CONTROLS.CFG']:
   if controls.exists():tracked.append(controls)
  snapshot={str(p):sha(p) for p in tracked}
  choices=list(hashes)+list(reversed(list(hashes)))+[(False,0)]
  for wide,level in choices:
   prepare(wide,level)
   config=(data/'dosbox.conf').read_text()
   chosen=game/(m['derived'] if wide or level or m.get('always_apply') else profile['program'])
   assert sha(chosen)==hashes[(wide,level)],(key,wide,level,sha(chosen))
   assert ('aspect = stretch' in config)==wide
   assert ('shader = trilogy-widescreen' in config)==wide
   assert ('window_size = 1280x720' in config)==wide
   assert ('\ncd SR\n' in config)==(key=='screamerrally')
   assert '\n'+chosen.name+'\n' in config
   assert {str(p):sha(p) for p in tracked}==snapshot
  assert not(data/'settings.json').exists()
  checks.append(f'{len(hashes)} independent mode hashes; toggle/repeat launches, DOS paths, original executable, settings and save preservation passed')
  if key=='screamer2':
   before=(data/'dosbox.conf').read_bytes()
   assert 'not supported' in prepare(True,2,1).stderr
   assert before==(data/'dosbox.conf').read_bytes()
   checks.append('Unsupported farther mode refused without changing config')
  saved={'widescreen':True,'extended_distance':True,'show_options':True}
  (data/'settings.json').write_text(json.dumps(saved))
  result=subprocess.run([str(executable),'--prepare-only','--data-dir',str(data)],capture_output=True,text=True,timeout=12)
  assert result.returncode==0,result.stdout+result.stderr
  assert sha(game/m['derived'])==hashes[(True,1)]
  assert json.loads((data/'settings.json').read_text())==saved
  checks.append('Legacy checkbox preferences migrate to extended level without showing or rewriting settings')
  saved['distance_level']=len(profile['distance_options'])-1
  (data/'settings.json').write_text(json.dumps(saved))
  subprocess.run([str(executable),'--prepare-only','--data-dir',str(data)],check=True,capture_output=True,timeout=12)
  assert sha(game/m['derived'])==hashes[(True,saved['distance_level'])]
  assert {str(p):sha(p) for p in tracked}==snapshot
  checks.append('Remembered distance level honored; CLI overrides remain temporary')
 assert sha(source)==m['sha256']
 return {'game':key,'app':str(app),'result':'passed','checks':checks,'mode_count':len(hashes)}

def main():
 global S1_HASHES
 source = Path(__file__).resolve().parent.parent/'src/patch-source-metadata.json'
 if not source.exists(): source = Path(__file__).resolve().parent.parent/'patch-source-metadata.json'
 variants = next(x['variants'] for x in json.loads(source.read_text())['games'] if x['game']=='screamer')
 S1_HASHES = {(x['widescreen'], x.get('distance_level',int(x['extended_distance']))): x['sha256'] for x in variants}
 parser=argparse.ArgumentParser();parser.add_argument('--release',type=Path,required=True);parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
 results=[verify(key,args.release/key/f'{title}.app') for key,title in TITLES.items()]
 args.report.write_text(json.dumps(results,indent=2)+'\n')
 print(json.dumps(results,indent=2))
if __name__=='__main__':main()
