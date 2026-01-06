# test_influxdb_direct.py - FIXED VERSION

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_influxdb():
    from django_tenants.utils import schema_context
    from companyadmin.models import AssetConfig
    
    with schema_context('sisaitech'):
        asset_config = AssetConfig.objects.filter(is_active=True).first()
        
        if not asset_config:
            print("❌ No AssetConfig found!")
            return
        
        print("="*100)
        print("🔍 DIRECT INFLUXDB DATA CHECK")
        print("="*100)
        print(f"Database: {asset_config.db_name}")
        print(f"API URL: {asset_config.base_api}")
        print(f"Username: {asset_config.api_username}")
        
        # TEST 1: Show all measurements
        print("\n📊 TEST 1: Show all measurements in database")
        query1 = 'SHOW MEASUREMENTS'
        
        try:
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={'db': asset_config.db_name, 'q': query1},
                auth=(asset_config.api_username, asset_config.api_password),
                verify=False,
                timeout=10
            )
            
            print(f"   Response status: {response.status_code}")
            data = response.json()
            
            if data.get('results') and data['results'][0].get('series'):
                measurements = [m[0] for m in data['results'][0]['series'][0]['values']]
                print(f"   Found {len(measurements)} measurements:")
                for m in measurements[:10]:  # Show first 10
                    print(f"      - {m}")
                if len(measurements) > 10:
                    print(f"      ... and {len(measurements) - 10} more")
            else:
                print(f"   ❌ No measurements found")
                print(f"   Response: {data}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # TEST 2: Show all field keys for chiller_a0hex001
        print("\n📊 TEST 2: Show field keys in 'chiller_a0hex001' measurement")
        query2 = 'SHOW FIELD KEYS FROM "chiller_a0hex001"'
        
        try:
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={'db': asset_config.db_name, 'q': query2},
                auth=(asset_config.api_username, asset_config.api_password),
                verify=False,
                timeout=10
            )
            
            data = response.json()
            print(f"   Response: {data}")
            
            if data.get('results') and data['results'][0].get('series'):
                fields = data['results'][0]['series'][0]['values']
                print(f"   Found {len(fields)} fields:")
                for field in fields:
                    print(f"      - {field[0]} (type: {field[1]})")
            else:
                print("   ❌ No fields found or measurement doesn't exist!")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # TEST 3: Show all tag keys
        print("\n📊 TEST 3: Show tag keys in 'chiller_a0hex001' measurement")
        query3 = 'SHOW TAG KEYS FROM "chiller_a0hex001"'
        
        try:
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={'db': asset_config.db_name, 'q': query3},
                auth=(asset_config.api_username, asset_config.api_password),
                verify=False,
                timeout=10
            )
            
            data = response.json()
            
            if data.get('results') and data['results'][0].get('series'):
                tags = data['results'][0]['series'][0]['values']
                print(f"   Found {len(tags)} tags:")
                for tag in tags:
                    print(f"      - {tag[0]}")
            else:
                print("   ❌ No tags found")
                print(f"   Response: {data}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # TEST 4: Show all distinct device IDs
        print("\n📊 TEST 4: Show all distinct device IDs")
        query4 = 'SHOW TAG VALUES FROM "chiller_a0hex001" WITH KEY = "id"'
        
        try:
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={'db': asset_config.db_name, 'q': query4},
                auth=(asset_config.api_username, asset_config.api_password),
                verify=False,
                timeout=10
            )
            
            data = response.json()
            
            if data.get('results') and data['results'][0].get('series'):
                ids = data['results'][0]['series'][0]['values']
                print(f"   Found {len(ids)} device IDs:")
                for device_id in ids:
                    print(f"      - {device_id[1]}")
            else:
                print("   ❌ No device IDs found")
                print(f"   Response: {data}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # TEST 5: Get last 5 data points (any device, any field)
        print("\n📊 TEST 5: Get last 5 data points from 'chiller_a0hex001'")
        query5 = 'SELECT * FROM "chiller_a0hex001" ORDER BY time DESC LIMIT 5'
        
        try:
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={'db': asset_config.db_name, 'q': query5},
                auth=(asset_config.api_username, asset_config.api_password),
                verify=False,
                timeout=10
            )
            
            data = response.json()
            
            if data.get('results') and data['results'][0].get('series'):
                series = data['results'][0]['series'][0]
                columns = series['columns']
                values = series['values']
                
                print(f"   Columns: {columns}")
                print(f"   Last {len(values)} data points:")
                for i, row in enumerate(values, 1):
                    print(f"\n      Point {i}:")
                    for j, col in enumerate(columns):
                        print(f"         {col}: {row[j]}")
            else:
                print("   ❌ No data found in measurement!")
                print(f"   Response: {data}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # TEST 6: Try different time ranges for AI1
        print("\n📊 TEST 6: Try AI1 with different time ranges")
        
        time_ranges = [
            ('5 minutes', 'now() - 5m'),
            ('1 hour', 'now() - 1h'),
            ('24 hours', 'now() - 24h'),
            ('7 days', 'now() - 7d')
        ]
        
        for label, time_range in time_ranges:
            query = f'SELECT last("AI1") FROM "chiller_a0hex001" WHERE "id" = \'chiller_a0hex001\' AND time >= {time_range}'
            
            try:
                response = requests.get(
                    f"{asset_config.base_api}/query",
                    params={'db': asset_config.db_name, 'q': query},
                    auth=(asset_config.api_username, asset_config.api_password),
                    verify=False,
                    timeout=10
                )
                
                data = response.json()
                
                if data.get('results') and data['results'][0].get('series'):
                    series = data['results'][0]['series'][0]
                    value = series['values'][0]
                    print(f"   ✅ {label}: AI1 = {value[1]} at {value[0]}")
                else:
                    print(f"   ❌ {label}: No data")
            except Exception as e:
                print(f"   ❌ {label}: Error - {e}")
        
        print("\n" + "="*100)

# Run the test
test_influxdb()