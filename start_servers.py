import sys
import subprocess
import threading
import time
import os

def tail_process(process, prefix):
    for line in iter(process.stdout.readline, b''):
        try:
            print(f"{prefix} {line.decode('utf-8', errors='replace').rstrip()}")
        except Exception:
            pass

def main():
    print("=======================================")
    print(" NextChord - 統合一発起動スクリプト")
    print("=======================================")
    
    # ゾンビプロセスの事前キル
    try:
        os.system('for /f "tokens=5" %a in (\'netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"\') do taskkill /F /PID %a >nul 2>&1')
        os.system('for /f "tokens=5" %a in (\'netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"\') do taskkill /F /PID %a >nul 2>&1')
    except Exception:
        pass

    backend_cmd = [
        "D:\\Music\\nextchord\\venv312\\Scripts\\python.exe",
        "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"
    ]
    
    frontend_env = os.environ.copy()
    frontend_env["CI"] = "true"  
    
    frontend_cmd = ["cmd", "/c", "npm run dev"]
    
    print("[1/2] Starting Backend...  (Port 8000)")
    p_backend = subprocess.Popen(
        backend_cmd,
        cwd="D:\\Music\\nextchord\\fastapi-backend",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1
    )
    
    print("[2/2] Starting Frontend... (Port 5173)")
    p_frontend = subprocess.Popen(
        frontend_cmd,
        cwd="D:\\Music\\nextchord\\nextchord-ui",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=frontend_env,
        bufsize=1
    )
    
    t_backend = threading.Thread(target=tail_process, args=(p_backend, "[BACKEND] "))
    t_frontend = threading.Thread(target=tail_process, args=(p_frontend, "[FRONTEND]"))
    
    t_backend.daemon = True
    t_frontend.daemon = True
    t_backend.start()
    t_frontend.start()
    
    print("\n>>> Done! \n>>> Backend: http://localhost:8000 \n>>> Frontend: http://localhost:5173")
    print(">>> 終了時は [Ctrl+C] を押してください。\n")
    
    try:
        while True:
            time.sleep(1)
            if p_backend.poll() is not None:
                print("=======================================")
                print("[!] Backend が予期せず終了しました。")
                print("=======================================")
                break
            if p_frontend.poll() is not None:
                print("=======================================")
                print("[!] Frontend が予期せず終了しました。")
                print("=======================================")
                break
    except KeyboardInterrupt:
        print("\n[Ctrl+C] シャットダウンシグナルを受け取りました...")
    finally:
        print("プロセスを停止中...")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p_backend.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p_frontend.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        print("終了しました。")
        sys.exit(0)

if __name__ == "__main__":
    main()
