import base64, hashlib, json, socket, struct, threading, unittest
from datetime import datetime, timezone, timedelta
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import app

def connection(up=0, down=0, ident='a', host='video.googlevideo.com', process='', chains=None):
    return {'id':ident,'start':datetime.now(timezone.utc).isoformat(),'upload':up,'download':down,'metadata':{'host':host,'process':process},'chains':chains or ['node A','PROXY']}

class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.r=app.Recorder(self.tmp.name+'/stats.db')
    def tearDown(self):
        self.r.db.close(); self.tmp.cleanup()
    def feed(self,*items, now=None): self.r.ingest({'connections':list(items)},now)
    def total(self): return sum(r['total'] for r in self.r.query('2000-01-01','2100-01-01')['rows'])
    def test_deltas_no_duplicate_and_final_disconnect(self):
        self.feed(connection(2,10)); self.feed(connection(5,15)); self.feed(connection(5,15)); self.feed(connection(6,23)); self.feed()
        self.assertEqual(self.total(),17)
    def test_new_connection_and_reset(self):
        self.feed(); self.feed(connection(3,20)); self.feed(connection(1,2)); self.feed(connection(2,5))
        self.assertEqual(self.total(),27)
    def test_old_unseen_connection_is_baseline(self):
        self.feed(); c=connection(1,100); c['start']='2000-01-01T00:00:00Z'; self.feed(c); self.assertEqual(self.total(),0)
    def test_reconnect_skips_gap(self):
        self.feed(connection(down=10)); self.feed(connection(down=20)); self.r.reconnect(); self.feed(connection(down=100)); self.feed(connection(down=103)); self.assertEqual(self.total(),13)
    def test_midnight_and_persistence(self):
        a=datetime(2026,10,3,23,59,tzinfo=timezone(timedelta(hours=8))); b=a+timedelta(minutes=2)
        self.feed(connection(down=10),now=a); self.feed(connection(down=20),now=a); self.feed(connection(down=25),now=b)
        self.assertEqual(self.r.query('2026-10-03','2026-10-03')['rows'][0]['total'],10)
        self.assertEqual(self.r.query('2026-10-04','2026-10-04')['rows'][0]['total'],5)
        r2=app.Recorder(self.tmp.name+'/stats.db'); self.assertEqual(sum(r['total'] for r in r2.query('2026-10-03','2026-10-04')['rows']),15); r2.db.close()
    def test_classification_and_routes(self):
        self.assertEqual(app.classify(connection())[0],'YouTube')
        self.assertEqual(app.classify(connection(host='api.openai.com'))[0],'OpenAI（共享/未区分）')
        self.assertEqual(app.classify(connection(host='api.openai.com',process='codex.exe'))[0],'Codex')
        self.assertEqual(app.classify(connection(host='fakegooglevideo.com'))[0],'fakegooglevideo.com')
        self.assertEqual(app.classify(connection(chains=['DIRECT','policy']))[3],'直连')
        self.assertEqual(app.classify(connection(chains=['node','policy']))[3],'代理')
    def test_filter_and_dimensions(self):
        self.feed(); self.feed(connection(down=5),connection(down=20,ident='b',chains=['DIRECT'],process='browser.exe'))
        self.assertEqual(self.r.query('2000-01-01','2100-01-01',route='代理')['rows'][0]['total'],5)
        self.assertEqual(len(self.r.query('2000-01-01','2100-01-01',dimension='process')['rows']),2)
        with self.assertRaises(ValueError):self.r.query('a','b',dimension='DROP TABLE traffic')
    def test_time_sort_with_nulls_and_filters(self):
        with self.r.db:
            self.r.db.executemany('INSERT INTO traffic(day,service,domain,process,route,upload,download,last_activity) VALUES(?,?,?,?,?,?,?,?)', [
                ('2026-10-16','Older','old.example','p','代理',0,500,1000),
                ('2026-10-16','Newer','new.example','p','代理',0,10,2000),
                ('2026-10-16','Unknown','unknown.example','p','代理',0,1000,None),
                ('2026-10-16','Older','old.example','p','直连',0,50,3000),
                ('2026-10-15','Outside','outside.example','p','代理',0,100,4000),
            ])
        def names(sort, route='全部'):
            return [r['name'] for r in self.r.query('2026-10-16','2026-10-16',route=route,sort=sort)['rows']]
        self.assertEqual(names('time_desc'),['Older','Newer','Unknown'])
        self.assertEqual(names('time_asc'),['Newer','Older','Unknown'])
        self.assertEqual(names('time_desc','代理'),['Newer','Older','Unknown'])
        self.assertEqual(names('traffic_desc'),['Unknown','Older','Newer'])
        self.assertEqual(names('traffic_asc'),['Newer','Older','Unknown'])
        with self.assertRaises(ValueError):self.r.query('a','b',sort='invalid')
    def test_activity_only_updates_with_new_bytes(self):
        a=datetime(2026,10,16,12,tzinfo=timezone.utc)
        self.feed(connection(down=10),now=a)
        self.feed(connection(down=15),now=a+timedelta(seconds=10))
        self.feed(connection(down=15),now=a+timedelta(seconds=20))
        row=self.r.query('2026-10-16','2026-10-16')['rows'][0]
        self.assertEqual(row['last_activity'],(a+timedelta(seconds=10)).timestamp())
        self.assertEqual(row['total'],5)
    def test_old_database_migration_preserves_totals(self):
        path=self.tmp.name+'/legacy.db'
        with app.sqlite3.connect(path) as db:
            db.execute('CREATE TABLE traffic(day TEXT, service TEXT, domain TEXT, process TEXT, route TEXT, upload INTEGER, download INTEGER, PRIMARY KEY(day,service,domain,process,route))')
            db.execute("INSERT INTO traffic VALUES('2026-10-16','Legacy','old.example','p','直连',12,34)")
        migrated=app.Recorder(path)
        try:
            row=migrated.query('2026-10-16','2026-10-16',sort='time_desc')['rows'][0]
            self.assertEqual(row['total'],46)
            self.assertIsNone(row['last_activity'])
            self.assertEqual(row['routes'][0]['name'],'直连')
            migrated.ingest({'connections':[]})
            c=connection(up=3,down=7,host='old.example',chains=['DIRECT'])
            migrated.ingest({'connections':[c]})
            self.assertEqual(sum(r['total'] for r in migrated.query('2026-01-01','2100-01-01')['rows']),56)
        finally:migrated.db.close()
    def test_minute_bounds_and_no_daily_double_count(self):
        a=datetime(2026,10,17,10,0,0)
        self.feed(connection(down=0),now=a)
        for seconds,download in [(59,10),(60,30),(119,60),(120,100)]:
            self.feed(connection(down=download),now=a+timedelta(seconds=seconds))
        def total(start,end):
            return sum(r['total'] for r in self.r.query(start,end)['rows'])
        self.assertEqual(total('2026-10-17T10:01','2026-10-17T10:01'),50)
        self.assertEqual(total('2026-10-17T10:00','2026-10-17T10:01'),60)
        self.assertEqual(total('2026-10-17T10:02','2026-10-17T10:02'),40)
        self.assertEqual(total('2026-10-17','2026-10-17'),100)
        with self.r.db:
            self.r.db.execute("INSERT INTO traffic(day,service,domain,process,route,upload,download) VALUES('2026-10-17','Legacy','legacy','p','代理',0,1000)")
        self.assertEqual(total('2026-10-17','2026-10-17'),1100)
        self.assertEqual(total('2026-10-17T00:00','2026-10-17T23:59'),100)
        with self.assertRaises(ValueError):self.r.query('2026-10-17T10:02','2026-10-17T10:01')
        with self.assertRaises(ValueError):self.r.query('2026-10-17T10:01:01','2026-10-17T10:02')
    def test_minute_timezone_filter_and_persistence(self):
        a=datetime(2026,10,17,23,59,0,tzinfo=timezone(timedelta(hours=8)))
        self.feed(connection(down=0),now=a)
        self.feed(connection(down=30),now=a+timedelta(seconds=59))
        self.feed(connection(down=70),now=a+timedelta(seconds=60))
        result=self.r.query('2026-10-17T23:59+08:00','2026-10-18T00:00+08:00',route='代理',sort='time_desc')
        self.assertEqual(result['rows'][0]['total'],70)
        self.assertEqual(len(result['daily']),2)
        self.assertEqual(result['resolution'],'minute')
        self.assertEqual(self.r.query('2026-10-17T23:59+08:00','2026-10-18T00:00+08:00',route='直连')['rows'],[])
        r2=app.Recorder(self.tmp.name+'/stats.db')
        try:
            self.assertEqual(r2.minute_started_at,self.r.minute_started_at)
            self.assertEqual(r2.query('2026-10-17T23:59+08:00','2026-10-18T00:00+08:00')['rows'][0]['total'],70)
        finally:r2.db.close()
    def test_config_validation(self):
        for url in ['http://example.com:9090','http://localhost:9090/path','http://u:p@localhost:9090','http://localhost:99999','http://127.0.0.1:9090?x=y']:
            with self.assertRaises(ValueError):app.validate_config({**app.DEFAULT,'controller':url})
        self.assertEqual(app.validate_config(app.DEFAULT.copy())['interval'],500)

class WebSocketTests(unittest.TestCase):
    def test_handshake_fragment_ping_and_snapshot(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]; errors=[]
        def server():
            try:
                s,_=listener.accept();s.settimeout(3);request=b''
                while b'\r\n\r\n' not in request:request+=s.recv(4096)
                self.assertIn(b'Authorization: Bearer test-secret',request)
                self.assertIn(b'/connections?interval=500',request)
                key=next(line.split(b':',1)[1].strip() for line in request.split(b'\r\n') if line.startswith(b'Sec-WebSocket-Key:'))
                accept=base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                s.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n')
                s.sendall(b'\x01\x10{"connections":['+b'\x89\x01X'+b'\x80\x02]}')
                pong=s.recv(1024);self.assertEqual(pong[0],138);self.assertTrue(pong[1]&128)
                s.close()
            except Exception as e:errors.append(e)
            finally:listener.close()
        t=threading.Thread(target=server);t.start();ws=app.WebSocket({**app.DEFAULT,'controller':f'http://127.0.0.1:{port}','secret':'test-secret'})
        self.assertEqual(ws.receive(),{'connections':[]});ws.close();t.join(5);self.assertFalse(errors,errors)
    def test_unauthorized(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
        def server():
            s,_=listener.accept();s.recv(4096);s.sendall(b'HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n');s.close();listener.close()
        t=threading.Thread(target=server);t.start()
        with self.assertRaisesRegex(ValueError,'认证失败'):app.WebSocket({**app.DEFAULT,'controller':f'http://127.0.0.1:{port}'})
        t.join()

class HTTPTests(unittest.TestCase):
    def test_api_and_export_and_config_auth(self):
        with TemporaryDirectory() as tmp:
            r=app.Recorder(tmp+'/db');app.RECORDER=r;r.ingest({'connections':[]});c=connection(down=2048,host='=danger');r.ingest({'connections':[c]})
            server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever);thread.start();base=f'http://127.0.0.1:{server.server_port}'
            try:
                html=urlopen(base).read();self.assertIn('流量账本'.encode(),html)
                s=json.load(urlopen(base+'/api/status'));self.assertNotIn('secret',s);self.assertIn('token',s)
                rows=json.load(urlopen(base+'/api/stats?start=2000-01-01&end=2100-01-01'));self.assertEqual(rows['rows'][0]['total'],2048)
                csv=urlopen(base+'/api/export?start=2000-01-01&end=2100-01-01').read().decode('utf-8-sig');self.assertIn("'=danger",csv)
                with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/config',data=b'{}',method='POST'))
                self.assertEqual(e.exception.code,403)
                with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/status',headers={'Host':'evil.example'}))
                self.assertEqual(e.exception.code,403)
            finally:server.shutdown();server.server_close();thread.join();r.db.close()

if __name__=='__main__':unittest.main()
