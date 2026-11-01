import os
import subprocess
import time

source_config = {
    'db_name': 'source_db', 'user': 'postgres',
    'password': 'secret', 'host': 'source_postgres'
}
destination_config = {
    'db_name': 'destination_db', 'user': 'postgres',
    'password': 'secret', 'host': 'destination_postgres'
}

def env_for(config):
    return {**os.environ, 'PGPASSWORD': config['password']}

def wait_for_postgres(host, max_retries=10, delay_seconds=5):
    for attempt in range(1, max_retries + 1):
        result = subprocess.run(["pg_isready", "-h", host],
                                capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Postgres is ready on {host}")
            return True
        print(f"{host} not ready (attempt {attempt}/{max_retries}), "
              f"retrying in {delay_seconds}s...")
        time.sleep(delay_seconds)
    return False

def check_table_exists(config, table_name):
    query = ("SELECT EXISTS (SELECT 1 FROM information_schema.tables "
             f"WHERE table_schema = 'public' AND table_name = '{table_name}');")
    cmd = ['psql', '-h', config['host'], '-U', config['user'],
           '-d', config['db_name'], '-t', '-A', '-c', query]
    out = subprocess.run(cmd, env=env_for(config), check=True,
                         capture_output=True, text=True).stdout.strip()
    return out == 't'

# Wait for BOTH databases
for cfg in (source_config, destination_config):
    if not wait_for_postgres(cfg['host']):
        print(f"{cfg['host']} is not ready. Exiting.")
        exit(1)

print("Starting ETL process...")

# Step 1: dump from source
print("Starting pg_dump...")
try:
    subprocess.run(
        ['pg_dump', '-h', source_config['host'], '-U', source_config['user'],
         '-d', source_config['db_name'], '--clean', '--if-exists',
         '-f', 'data_dump.sql', '-w'],
        env=env_for(source_config), check=True)
    print("Data dump completed successfully.")
except subprocess.CalledProcessError as e:
    print(f"Error during pg_dump: {e}")
    exit(1)

# Step 2: load into destination (stop on first error)
print("Loading data into destination...")
try:
    subprocess.run(
        ['psql', '-h', destination_config['host'], '-U', destination_config['user'],
         '-d', destination_config['db_name'], '-v', 'ON_ERROR_STOP=1',
         '-f', 'data_dump.sql', '-w'],
        env=env_for(destination_config), check=True)
    print("Data load completed successfully.")
except subprocess.CalledProcessError as e:
    print(f"Error during psql load: {e}")
    exit(1)

# Step 3: verify (bounded retries, no infinite loop)
for _ in range(6):
    if check_table_exists(destination_config, "films"):
        print("films table found in destination. ETL finished.")
        break
    print("films table not found yet, waiting 5 seconds...")
    time.sleep(5)
else:
    print("films table never appeared. Something went wrong.")
    exit(1)