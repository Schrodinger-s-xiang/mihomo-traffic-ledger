"""Local Mihomo traffic recorder. Python 3.10+, standard library only."""
import base64, csv, hashlib, io, json, os, secrets, socket, sqlite3, struct, threading, time, webbrowser, sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

VERSION = '1.4.0'
ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
# pythonw has no console streams; retain startup/errors locally for diagnosis.
if __name__ == '__main__' and (sys.stdout is None or sys.stderr is None):
    _background_log = open(DATA / 'background.log', 'a', encoding='utf-8', buffering=1)
    if sys.stdout is None:
        sys.stdout = _background_log
    if sys.stderr is None:
        sys.stderr = _background_log
LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(32)
STATUS = {'connected': False, 'message': '等待连接', 'last_update': None, 'active': 0}
DEFAULT = {'controller': 'http://127.0.0.1:9090', 'secret': '', 'interval': 500}
CONFIG = DEFAULT.copy()
try:
    CONFIG.update(json.loads((DATA/'config.json').read_text('utf-8')))
except (OSError, ValueError):
    pass
REVISION = 0
STOP = threading.Event()

def validate_config(c):
    p = urlparse(c['controller'])
    if p.scheme != 'http' or p.hostname not in ('localhost', '127.0.0.1', '::1') or p.path not in ('', '/') or p.username or p.password or p.query or p.fragment:
        raise ValueError('控制地址应为本机 HTTP 地址，例如 http://127.0.0.1:9090')
    port = p.port or 80
    if not 1 <= port <= 65535:
        raise ValueError('端口无效')
    if not isinstance(c['secret'], str) or any(x in c['secret'] for x in '\r\n'):
        raise ValueError('Secret 无效')
    c['interval'] = max(100, min(5000, int(c.get('interval', 500))))
    c['controller'] = c['controller'].rstrip('/')
    return c

SERVICES = [
 ('YouTube', ['youtube.com','youtu.be','googlevideo.com','ytimg.com','youtubei.googleapis.com','youtube-nocookie.com']),
 ('ChatGPT', ['chatgpt.com','chat.openai.com','oaistatic.com','oaiusercontent.com']),
 ('OpenAI（共享/未区分）', ['openai.com']),
 ('Google', ['google.com','googleapis.com','gstatic.com','googleusercontent.com']),
 ('GitHub', ['github.com','githubusercontent.com','githubassets.com']),
 ('哔哩哔哩', ['bilibili.com','bilivideo.com','hdslb.com']),
 ('网易云音乐', ['music.163.com','music.126.net']),
 ('Telegram', ['telegram.org','t.me']),
 ('Microsoft', ['microsoft.com','live.com','windows.net','office.com'])]

def classify(c):
    m = c.get('metadata') or {}
    host = str(m.get('host') or m.get('destinationIP') or '未知目标').lower().rstrip('.')
    proc = str(m.get('process') or m.get('processPath') or '').replace('\\','/').split('/')[-1] or '未识别进程'
    if 'codex' in proc.lower():
        service = 'Codex'
    elif proc.lower() in ('chatgpt.exe', 'chatgpt'):
        service = 'ChatGPT'
    else:
        service = host
        for label, domains in SERVICES:
            if any(host == d or host.endswith('.'+d) for d in domains):
                service = label
                break
    chains = [str(x) for x in (c.get('chains') or [])]
    # Mihomo chains are ordered from final outbound to policy groups.
    leaf = chains[0].upper() if chains else ''
    route = '直连' if leaf in ('DIRECT','COMPATIBLE') else ('拦截' if leaf in ('REJECT','REJECT-DROP') else ('代理' if leaf else '未知'))
    return service, host, proc, route

class Recorder:
    def __init__(self, db):
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS traffic(day TEXT, service TEXT, domain TEXT, process TEXT, route TEXT, upload INTEGER, download INTEGER, PRIMARY KEY(day,service,domain,process,route))')
        # Keep existing daily totals; older records have no recoverable activity time.
        with self.db:
            columns = {row[1] for row in self.db.execute('PRAGMA table_info(traffic)')}
            if 'last_activity' not in columns:
                self.db.execute('ALTER TABLE traffic ADD COLUMN last_activity REAL')
            self.db.execute('CREATE TABLE IF NOT EXISTS minute_traffic(bucket INTEGER, day TEXT, service TEXT, domain TEXT, process TEXT, route TEXT, upload INTEGER, download INTEGER, last_activity REAL, PRIMARY KEY(bucket,service,domain,process,route))')
            self.db.execute('CREATE TABLE IF NOT EXISTS recorder_meta(key TEXT PRIMARY KEY, value TEXT)')
            self.db.execute("INSERT OR IGNORE INTO recorder_meta VALUES('minute_started_at',?)", (str(time.time()),))
        self.minute_started_at = float(self.db.execute("SELECT value FROM recorder_meta WHERE key='minute_started_at'").fetchone()[0])
        self.previous = {}
        self.session_start = time.time()
        self.baseline = True
    def reconnect(self):
        self.previous = {}
        self.baseline = True
        self.session_start = time.time()
    def ingest(self, snapshot, now=None):
        now = now or datetime.now().astimezone()
        live = {}
        with LOCK, self.db:
            for c in snapshot.get('connections') or []:
                ident = str(c.get('id') or '')
                if not ident:
                    continue
                up, down = max(0, int(c.get('upload') or 0)), max(0, int(c.get('download') or 0))
                old = self.previous.get(ident)
                live[ident] = (up, down)
                if old:
                    du, dd = max(0,up-old[0]), max(0,down-old[1])
                elif self.baseline:
                    du = dd = 0
                else:
                    try:
                        started = datetime.fromisoformat(c.get('start','').replace('Z','+00:00')).timestamp()
                    except (ValueError, TypeError):
                        started = 0
                    du, dd = (up,down) if started >= self.session_start else (0,0)
                if du or dd:
                    dims = classify(c)
                    self.db.execute('INSERT INTO traffic(day,service,domain,process,route,upload,download,last_activity) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(day,service,domain,process,route) DO UPDATE SET upload=upload+excluded.upload,download=download+excluded.download,last_activity=MAX(COALESCE(last_activity,excluded.last_activity),excluded.last_activity)', (now.date().isoformat(), *dims, du, dd, now.timestamp()))
                    self.db.execute('INSERT INTO minute_traffic VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(bucket,service,domain,process,route) DO UPDATE SET upload=upload+excluded.upload,download=download+excluded.download,last_activity=MAX(last_activity,excluded.last_activity)', (int(now.timestamp())//60*60, now.date().isoformat(), *dims, du, dd, now.timestamp()))
            self.previous = live
            self.baseline = False
    def query(self, start, end, dimension='service', route='全部', sort='traffic_desc'):
        if dimension not in ('service','domain','process','route'):
            raise ValueError('分组无效')
        orders = {
            'traffic_desc': 'SUM(upload+download) DESC, '+dimension+' ASC',
            'traffic_asc': 'SUM(upload+download) ASC, '+dimension+' ASC',
            'time_desc': 'MAX(last_activity) IS NULL, MAX(last_activity) DESC, '+dimension+' ASC',
            'time_asc': 'MAX(last_activity) IS NULL, MAX(last_activity) ASC, '+dimension+' ASC',
        }
        if sort not in orders:
            raise ValueError('排序无效')
        precise = 'T' in start or 'T' in end
        if precise:
            def minute(value, end_value=False):
                dt = datetime.fromisoformat(value)
                if dt.second or dt.microsecond:
                    raise ValueError('请精确到分钟')
                return int(dt.timestamp())//60*60 + (86400-60 if end_value and 'T' not in value else 0)
            lower, upper = minute(start), minute(end,True)
            if lower>upper:
                raise ValueError('开始时间不能晚于结束时间')
            table, where, args = 'minute_traffic', 'bucket BETWEEN ? AND ?', [lower,upper]
        else:
            lower,upper=datetime.fromisoformat(start).date(),datetime.fromisoformat(end).date()
            if lower>upper:
                raise ValueError('开始日期不能晚于结束日期')
            table, where, args = 'traffic', 'day BETWEEN ? AND ?', [start,end]
        if route != '全部':
            if route not in ('代理','直连','拦截','未知'):
                raise ValueError('出口无效')
            where += ' AND route=?'
            args.append(route)
        with LOCK:
            rows = self.db.execute(f'SELECT {dimension},SUM(upload),SUM(download),MAX(last_activity) FROM {table} WHERE {where} GROUP BY {dimension} ORDER BY {orders[sort]}',args).fetchall()
            exits = self.db.execute(f'SELECT {dimension},route,SUM(upload),SUM(download) FROM {table} WHERE {where} GROUP BY {dimension},route ORDER BY SUM(upload+download) DESC',args).fetchall()
            daily = self.db.execute(f'SELECT day,SUM(upload),SUM(download) FROM {table} WHERE {where} GROUP BY day ORDER BY day',args).fetchall()
        routes = {}
        for name, exit_type, up, down in exits:
            routes.setdefault(name, []).append({'name': exit_type, 'upload': up, 'download': down, 'total': up+down})
        return {'time_tracking':True,'minute_tracking':True,'resolution':'minute' if precise else 'day','minute_started_at':self.minute_started_at,'rows':[{'name':n,'upload':u,'download':d,'total':u+d,'routes':routes.get(n,[]),'last_activity':last} for n,u,d,last in rows], 'daily':[{'day':n,'upload':u,'download':d,'total':u+d} for n,u,d in daily]}

class WebSocket:
    """RFC6455 client for a local unencrypted Mihomo snapshot stream."""
    def __init__(self, config):
        p = urlparse(config['controller'])
        self.sock = socket.create_connection((p.hostname, p.port or 80), timeout=8)
        self.sock.settimeout(10)
        self.buffer = b''
        key = base64.b64encode(os.urandom(16)).decode()
        host = p.netloc
        request = f'GET /connections?interval={config["interval"]} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
        if config['secret']:
            request += 'Authorization: Bearer '+config['secret']+'\r\n'
        try:
            self.sock.sendall((request+'\r\n').encode())
            response = b''
            while b'\r\n\r\n' not in response:
                response += self.exact(1)
                if len(response)>65536:
                    raise ValueError('API 响应头过大')
            lines = response.decode('latin1').split('\r\n')
            if ' 101 ' not in lines[0]:
                if ' 401 ' in lines[0]:
                    raise ValueError('认证失败，请检查 Secret')
                raise ValueError('控制接口未接受 WebSocket，请检查 API 控制端口')
            headers = dict(line.split(':',1) for line in lines[1:] if ':' in line)
            accept = next((v.strip() for k,v in headers.items() if k.lower()=='sec-websocket-accept'), '')
            expected = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if accept != expected:
                raise ValueError('WebSocket 握手验证失败')
        except Exception:
            self.close()
            raise
    def exact(self,n):
        while len(self.buffer)<n:
            chunk=self.sock.recv(max(4096,n-len(self.buffer)))
            if not chunk:
                raise ConnectionError('控制接口断开，正在重连')
            self.buffer+=chunk
        result,self.buffer=self.buffer[:n],self.buffer[n:]
        return result
    def send(self, opcode, data=b''):
        mask=os.urandom(4)
        self.sock.sendall(bytes([128|opcode,128|len(data)])+mask+bytes(v^mask[i%4] for i,v in enumerate(data)))
    def receive(self):
        payload=bytearray()
        while True:
            a,b=self.exact(2)
            if a&0x70 or b&0x80:
                raise ValueError('不支持的 WebSocket 帧')
            n=b&127
            if n==126: n=struct.unpack('!H',self.exact(2))[0]
            elif n==127: n=struct.unpack('!Q',self.exact(8))[0]
            if n>32*1024*1024 or len(payload)+n>32*1024*1024:
                raise ValueError('连接快照过大')
            data=self.exact(n); op=a&15
            if op==8: raise ConnectionError('控制接口断开，正在重连')
            if op==9:
                if n>125: raise ValueError('无效 ping')
                self.send(10,data); continue
            if op==10: continue
            if op not in (0,1): raise ValueError('控制接口返回了非文本快照')
            payload.extend(data)
            if a&128:
                return json.loads(payload)
    def close(self):
        self.sock.close()

RECORDER = None

def collect():
    global STATUS
    while not STOP.is_set():
        with LOCK:
            cfg, revision = CONFIG.copy(), REVISION
        ws=None
        try:
            validate_config(cfg)
            ws=WebSocket(cfg)
            RECORDER.reconnect()
            while not STOP.is_set():
                snapshot=ws.receive()
                if revision != REVISION: break
                RECORDER.ingest(snapshot)
                with LOCK:
                    STATUS.update(connected=True,message='持续记录中',last_update=datetime.now().astimezone().isoformat(),active=len(snapshot.get('connections') or []))
        except Exception as e:
            with LOCK:
                STATUS.update(connected=False,message=str(e) if isinstance(e,ValueError) else '无法连接控制接口，请检查 Clash 是否运行、控制端口和 Secret')
        finally:
            if ws: ws.close()
            with LOCK: STATUS['connected']=False
        STOP.wait(2)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_bytes(self,data,ctype='application/json; charset=utf-8',status=200):
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def reply(self,obj,status=200): self.send_bytes(json.dumps(obj,ensure_ascii=False).encode(),status=status)
    def trusted(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.trusted(): return self.reply({'error':'Host 无效'},403)
        p=urlparse(self.path); q=parse_qs(p.query)
        try:
            if p.path=='/': return self.send_bytes((ROOT/'dashboard.html').read_bytes(),'text/html; charset=utf-8')
            if p.path=='/api/status':
                with LOCK:
                    return self.reply({**STATUS,'version':VERSION,'time_tracking':True,'minute_tracking':True,'controller':CONFIG['controller'],'has_secret':bool(CONFIG['secret']),'token':TOKEN,'timezone':str(datetime.now().astimezone().tzinfo)})
            if p.path in ('/api/stats','/api/export'):
                today=datetime.now().date()
                start=q.get('start',[today.isoformat()])[0]; end=q.get('end',[today.isoformat()])[0]
                result=RECORDER.query(start,end,q.get('dimension',['service'])[0],q.get('route',['全部'])[0],q.get('sort',['traffic_desc'])[0])
                if p.path=='/api/stats': return self.reply(result)
                out=io.StringIO(); writer=csv.writer(out); writer.writerow(['名称','上传字节','下载字节','总字节','最近活动时间（本机时区）'])
                for r in result['rows']:
                    # Prevent spreadsheet formula execution from observed host/process names.
                    name=r['name']; name="'"+name if name.startswith(('=','+','-','@','\t','\r')) else name
                    last = r['last_activity']
                    activity = datetime.fromtimestamp(last).astimezone().isoformat(timespec='seconds') if last is not None else '未记录'
                    writer.writerow([name,r['upload'],r['download'],r['total'],activity])
                return self.send_bytes(out.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8')
            return self.reply({'error':'未找到'},404)
        except (ValueError,TypeError): return self.reply({'error':'请求参数无效'},400)
    def do_POST(self):
        global CONFIG,REVISION
        if not self.trusted() or self.headers.get('X-Local-Token')!=TOKEN:
            return self.reply({'error':'认证失败'},403)
        if self.path!='/api/config': return self.reply({'error':'未找到'},404)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>8192: raise ValueError('请求过大')
            values=json.loads(self.rfile.read(n))
            with LOCK:
                cfg=CONFIG.copy(); cfg['controller']=values['controller']
                if values.get('clear_secret'): cfg['secret']=''
                elif values.get('secret'): cfg['secret']=values['secret']
                validate_config(cfg)
                temp=DATA/'config.tmp'; temp.write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8')
                try: os.chmod(temp,0o600)
                except OSError: pass
                temp.replace(DATA/'config.json')
                CONFIG=cfg; REVISION+=1
                STATUS.update(connected=False,message='配置已保存，正在连接')
            self.reply({'ok':True})
        except (ValueError,KeyError,TypeError): self.reply({'error':'地址应为 http://127.0.0.1:控制端口；Secret 不能含换行'},400)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--no-browser',action='store_true'); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    try: server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError:
        print('网页端口被占用：可能已经启动。请打开 http://127.0.0.1:'+str(args.port)+'，或使用 --port 8766'); raise SystemExit(1)
    RECORDER=Recorder(DATA/'traffic.sqlite3')
    threading.Thread(target=collect,daemon=True).start()
    url='http://127.0.0.1:'+str(args.port)
    print('Mihomo 流量统计器 v'+VERSION+'：'+url+'\n程序位置：'+str(ROOT)+'\n关闭窗口或 Ctrl+C 停止记录。历史数据在 data 文件夹。',flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        STOP.set(); server.server_close()
