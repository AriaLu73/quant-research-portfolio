"""终止 exit_mgmt_backtest.py 的批次进程及其子进程(2026-11-09:环境变量没传进 detach,误跑了 XBTUSDCM)。"""
import psutil
procs = []
for p in psutil.process_iter(['pid', 'cmdline']):
    cl = ' '.join(p.info['cmdline'] or [])
    if 'exit_mgmt_backtest' in cl and 'kill_exit' not in cl:
        procs.append(p)
        try:
            procs += p.children(recursive=True)
        except Exception:
            pass
for p in procs:
    try:
        print('kill', p.pid, ' '.join(p.cmdline())[-70:]); p.kill()
    except Exception as e:
        print('err', p.pid, e)
print('done', len(procs))
