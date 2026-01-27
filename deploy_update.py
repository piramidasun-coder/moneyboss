import paramiko
import time

HOST = "81.200.119.104"
USER = "root"
PASS = "GiT7753191"

print(f"Connecting to {HOST}...")

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, username=USER, password=PASS)
    
    print("Success! Connected.")
    
    # Команда обновления
    command = "sed -i 's|AI_MODEL=deepseek/deepseek-chat|AI_MODEL=google/gemini-flash-1.5|g' /root/moneyboss/.env && systemctl restart moneyboss && systemctl status moneyboss | grep Active"
    
    print("Updating configuration...")
    stdin, stdout, stderr = client.exec_command(command)
    
    # Ждем выполнения
    exit_status = stdout.channel.recv_exit_status()
    
    output = stdout.read().decode().strip()
    error = stderr.read().decode().strip()
    
    if exit_status == 0:
        print("\nSUCCESS! Bot updated and restarted.")
        print(f"Status: {output}")
    else:
        print("\nERROR:")
        print(error)
        
    client.close()

except Exception as e:
    print(f"\nCONNECTION FAILED: {e}")
