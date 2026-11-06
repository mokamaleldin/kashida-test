"""Local read-only dashboard. Viewing/filtering never calls a data provider."""
import http.server,json,pathlib,urllib.parse
from monitor import ROOT,connect,all_posts,costs

def serve(db_path,port):
 class Handler(http.server.BaseHTTPRequestHandler):
  def do_GET(self):
   path=urllib.parse.urlsplit(self.path).path
   if path=='/':body=(ROOT/'dashboard.html').read_bytes();kind='text/html; charset=utf-8'
   elif path=='/api/data':
    db=connect(db_path);posts=all_posts(db);db.close()
    report=json.loads((ROOT/'data/last_run.json').read_text()) if (ROOT/'data/last_run.json').exists() else {}
    body=json.dumps({'posts':posts,'report':report,'costs':[costs(n,m) for n in [50,60] for m in [15,30]]},ensure_ascii=False).encode();kind='application/json; charset=utf-8'
   else:self.send_error(404);return
   self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src https:; media-src https:; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
  def log_message(self,*args):pass
 server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler)
 print('Dashboard: http://127.0.0.1:'+str(port)+' (local only; no background collection)',flush=True)
 try:server.serve_forever()
 finally:server.server_close()
