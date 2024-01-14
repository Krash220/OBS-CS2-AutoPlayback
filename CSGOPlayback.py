import obspython as obs
import winreg
import os
import random
import base64
import json
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

scene_name = None
source_name = None

csi_path = None
http_server = None
token = None

event_stack = []
kill_type = []
playback_list = []
last_round = None
update_time = False

def update_playback_list():
    if kill_type:
        fn = obs.obs_frontend_get_last_replay()
        if fn and fn != last_round:
            hs = kill_type.pop(0)
            playback_list.append(fn)

            obs.script_log(obs.LOG_INFO, 'Added Playback: %s %s' % (str(hs), fn))

            if hs:
                playback_list.append(fn)
                playback_list.append(fn)

def update_last_round():
    global last_round
    last_round = obs.obs_frontend_get_last_replay()

def save_playback():
    update_playback_list()

    obs.obs_frontend_replay_buffer_save()

def start_playback():
    global update_time
    update_playback_list()

    if playback_list:
        fn = playback_list[random.randint(0, len(playback_list) - 1)]
        obs.script_log(obs.LOG_INFO, 'Choose Playback: %s' % fn)
        obs.script_log(obs.LOG_INFO, 'Playbacks: %s' % str(playback_list))
        playback_list.clear()

        scene = obs.obs_get_scene_by_name(scene_name)
        obs.obs_scene_get_source
        source = obs.obs_get_source_by_name(source_name)

        if scene and source:
            settings = obs.obs_source_get_settings(source)

            obs.obs_data_set_string(settings, 'local_file', fn)
            obs.obs_data_set_bool(settings, 'restart_on_activate', True)
            obs.obs_data_set_bool(settings, 'clear_on_media_end', False)
            obs.obs_data_set_int(settings, 'speed_percent', 33)
            obs.obs_source_update(source, settings)

            obs.obs_data_release(settings)

            item = obs.obs_scene_sceneitem_from_source(scene, source)

            obs.obs_sceneitem_set_visible(item, True)
            update_time = True

            obs.obs_sceneitem_release(item)
            obs.obs_source_release(source)
            obs.obs_source_release(obs.obs_scene_get_source(scene))

def stop_playback():
    scene = obs.obs_get_scene_by_name(scene_name)
    source = obs.obs_get_source_by_name(source_name)

    if scene and source:
        item = obs.obs_scene_sceneitem_from_source(scene, source)

        obs.obs_sceneitem_set_visible(item, False)

        obs.obs_sceneitem_release(item)
        obs.obs_source_release(source)
        obs.obs_source_release(obs.obs_scene_get_source(scene))

class CSGSIServer(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", 'application/text')
        self.send_header("Content-Length", 0)
        self.end_headers()
        self.wfile.flush()

    def do_POST(self):
        global last_is_hs

        cs = json.loads(self.rfile.read(int(self.headers.get('content-length'))).decode())

        if cs['auth']['token'] == token:
            prev = {}

            if 'previously' in cs:
                prev = cs['previously']

            if 'player' in cs and cs['provider']['steamid'] == cs['player']['steamid']:
                if 'map' in cs:
                    if cs['map']['phase'] == 'live' and cs['round']['phase'] in ['live', 'over']:
                        last_kills = kills = cs['player']['state']['round_kills']
                        last_killhs = killhs = cs['player']['state']['round_killhs']

                        if 'player' in prev and type(prev['player']) is dict and 'state' in prev['player']:
                            last_kills = prev['player']['state']['round_kills'] if 'round_kills' in prev['player']['state'] else kills
                            last_killhs = prev['player']['state']['round_killhs'] if 'round_killhs' in prev['player']['state'] else killhs

                        if killhs > last_killhs:
                            kill_type.append(True)
                            event_stack.append((time.time() + 1, save_playback))
                        elif kills > last_kills:
                            kill_type.append(False)
                            event_stack.append((time.time() + 1, save_playback))

                    if 'round' in prev and type(prev['round']) is dict and 'phase' in prev['round']:
                        if prev['round']['phase'] == 'freezetime' and cs['round']['phase'] == 'live':
                            kill_type.clear()
                            event_stack.append((time.time(), update_last_round))
                            obs.script_log(obs.LOG_INFO, 'Clear old playback.')
                        elif prev['round']['phase'] == 'live':
                            if cs['map']['phase'] == 'gameover':
                                event_stack.append((time.time() + 10, start_playback))
                            elif cs['round']['phase'] == 'over':
                                event_stack.append((time.time() + 2.5, start_playback))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", 'application/text')
        self.send_header("Content-Length", 0)
        self.end_headers()
        self.wfile.flush()
    
    def log_request(self, code='-', size='-'):
        pass

def http_thread():
    global token
    global http_server

    server = ThreadingHTTPServer(('127.0.0.1', 0), CSGSIServer)
    server.finish_request

    token = base64.b64encode(random.randbytes(18)).decode()
    cfg = """"OBS Playback"
{
 "uri" "http://127.0.0.1:""" + str(server.server_port) + """"
 "timeout" "0.1"
 "buffer"  "0.1"
 "throttle" "0.5"
 "heartbeat" "60.0"
 "auth"
 {
   "token" \"""" + token + """\"
 }
 "data"
 {
   "provider"            "1"
   "map"                 "1"
   "round"               "1"
   "player_id"           "1"
   "player_state"        "1"
 }
}
"""

    if os.path.exists(csi_path + 'csgo\\cfg'):
        with open(csi_path + 'csgo\\cfg\\gamestate_integration_obsplayback.cfg', 'w') as fd:
            fd.write(cfg)

    if os.path.exists(csi_path + 'game\\csgo\\cfg'):
        with open(csi_path + 'game\\csgo\\cfg\\gamestate_integration_obsplayback.cfg', 'w') as fd:
            fd.write(cfg)

    http_server = server
    http_server.serve_forever()

def script_tick(seconds):
    global update_time

    now = time.time()
    rem = []
    for item in event_stack:
        t, call = item
        if now > t:
            if obs.obs_frontend_replay_buffer_active():
                call()
            rem.append(item)

    for item in rem:
        event_stack.remove(item)

    if update_time:
        source = obs.obs_get_source_by_name(source_name)
        if source and obs.obs_source_media_get_state(source) == obs.OBS_MEDIA_STATE_PLAYING and obs.obs_source_media_get_time(source) > 50: # magic number
            ts = obs.obs_source_media_get_duration(source) - 2333
            ts = int((ts / 1000.0) + 0.5) * 1000
            event_stack.append((time.time() + (obs.obs_source_media_get_duration(source) - ts - 333) / 330.0, stop_playback))
            obs.obs_source_media_set_time(source, ts + 100)
            update_time = False
            obs.obs_source_release(source)

def script_load(settings):
    global csi_path

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\Valve\Steam', 0, winreg.KEY_READ)
        path, _ = winreg.QueryValueEx(key, 'SteamPath')
        winreg.CloseKey(key)
    except:
        obs.script_log(obs.LOG_ERROR, '无法获取Steam路径，脚本无法生效。')
        return

    libpath = path + '/steamapps/libraryfolders.vdf'

    with open(libpath, 'r') as libvdf:
        library = libvdf.readlines()
        last_path = None
        found = False

        for line in library:
            pair = line.strip('\n').strip('\t')
            if pair.startswith('"path"'):
                _, v = pair.split('\t\t')
                last_path = v.strip('"').encode().decode('unicode_escape')
            elif '"730"' in pair:
                found = True
                break

        if found and os.path.exists(last_path + '\\steamapps\\common\\Counter-Strike Global Offensive\\'):
            csi_path = last_path + '\\steamapps\\common\\Counter-Strike Global Offensive\\'
        else:
            obs.script_log(obs.LOG_ERROR, '无法获取CSGO游戏路径，脚本无法生效。')
            return

    threading.Thread(target=http_thread).start()

def script_unload():
    if http_server:
        http_server.shutdown()

    if os.path.exists(csi_path + 'csgo\\cfg\\gamestate_integration_obsplayback.cfg'):
        os.remove(csi_path + 'csgo\\cfg\\gamestate_integration_obsplayback.cfg')
    if os.path.exists(csi_path + 'game\\csgo\\cfg\\gamestate_integration_obsplayback.cfg'):
        os.remove(csi_path + 'game\\csgo\\cfg\\gamestate_integration_obsplayback.cfg')

def script_update(settings):
    global scene_name
    global source_name

    scene_name = obs.obs_data_get_string(settings, 'scene')
    source_name = obs.obs_data_get_string(settings, 'source')

def script_properties():
    props = obs.obs_properties_create()

    p_scene = obs.obs_properties_add_list(props, 'scene', 'Scene', obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
    p_source = obs.obs_properties_add_list(props, 'source', 'Source', obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)

    scenes = obs.obs_frontend_get_scenes()
    if scenes is not None:
        for scene in scenes:
            name = obs.obs_source_get_name(scene)
            obs.obs_property_list_add_string(p_scene, name, name)

        obs.source_list_release(scenes)

    sources = obs.obs_enum_sources()
    if sources is not None:
        for source in sources:
            source_id = obs.obs_source_get_unversioned_id(source)

            if source_id == 'ffmpeg_source':
                name = obs.obs_source_get_name(source)
                obs.obs_property_list_add_string(p_source, name, name)

        obs.source_list_release(sources)

    return props
