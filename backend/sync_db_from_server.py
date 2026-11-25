import os
import subprocess
from dotenv import load_dotenv

# Load local environment variables for the database
load_dotenv('.env')

# --- Server Details (Fill these in) ---
# You can hardcode these or enter them when the script runs
SERVER_IP = input("Enter your production server IP or Domain (e.g., 143.198.54.91): ").strip()
SERVER_USER = input("Enter your SSH username (e.g., root): ").strip()

# Optional: Path to your SSH key, leave blank if you use password authentication
SSH_KEY_PATH = input("Enter SSH Key path (leave blank if you use a password): ").strip()
# --------------------------------------

LOCAL_DB_NAME = os.getenv("DB_NAME", "rcdf_supply")
LOCAL_DB_USER = os.getenv("DB_USER", "root")
LOCAL_DB_PASS = os.getenv("DB_PASSWORD", "")

print(f"\n[1] Creating a backup of '{LOCAL_DB_NAME}' on the production server...")

ssh_cmd = ["ssh", f"{SERVER_USER}@{SERVER_IP}"]
if SSH_KEY_PATH:
    ssh_cmd = ["ssh", "-i", SSH_KEY_PATH, f"{SERVER_USER}@{SERVER_IP}"]

dump_cmd = ssh_cmd + ["mysqldump", "-u", "root", "-p", LOCAL_DB_NAME, ">", "rcdf_supply_backup.sql"]

print("-> Running: " + " ".join(dump_cmd))
print("-> Note: You may be prompted for your SERVER SSH password, and then the SERVER MySQL password.")

# Run the dump command on the remote server
subprocess.run(" ".join(dump_cmd), shell=True)

print(f"\n[2] Downloading the backup file from {SERVER_IP} to your local machine...")

scp_cmd = ["scp"]
if SSH_KEY_PATH:
    scp_cmd.extend(["-i", SSH_KEY_PATH])
scp_cmd.extend([f"{SERVER_USER}@{SERVER_IP}:~/rcdf_supply_backup.sql", "rcdf_supply_backup.sql"])

print("-> Running: " + " ".join(scp_cmd))
subprocess.run(scp_cmd)

print(f"\n[3] Importing the data into your local database '{LOCAL_DB_NAME}'...")

import_cmd = f"mysql -u {LOCAL_DB_USER} "
if LOCAL_DB_PASS:
    import_cmd += f"-p{LOCAL_DB_PASS} "
import_cmd += f"{LOCAL_DB_NAME} < rcdf_supply_backup.sql"

print("-> Running local import...")
subprocess.run(import_cmd, shell=True)

print("\n✅ Sync Complete! Your local database has been updated with the production data.")
