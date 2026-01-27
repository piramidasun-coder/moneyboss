import paramiko

HOST = "81.200.119.104"
USER = "root"
PASS = "GiT7753191"
NEW_API_KEY = "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"

print(f"Connecting to {HOST}...")

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, username=USER, password=PASS)
    
    print("Connected! Updating API key...")
    
    # Команда обновления ключа
    command = f"sed -i 's|AI_API_KEY=.*|AI_API_KEY={NEW_API_KEY}|g' /root/moneyboss/.env && systemctl restart moneyboss"
    
    stdin, stdout, stderr = client.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    
    if exit_status == 0:
        print("SUCCESS! API key updated and bot restarted.")
    else:
        print("ERROR:")
        print(stderr.read().decode())
        
    client.close()

except Exception as e:
    print(f"CONNECTION FAILED: {e}")
