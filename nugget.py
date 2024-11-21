import requests, hashlib, json, time, ovh, sys, os
from datetime import datetime
from random import randint

with open('config.json') as f: config = json.load(f)
with open('endpoints.json') as f: endpoints = json.load(f)
path = os.path.dirname(os.path.realpath(__file__))

if not "autoPay" in config: exit("autoPay missing in config.")
if not "switchRegion" in config: exit("switchRegion missing in config.")
if not "anyDatacenter" in config: exit("anyDatacenter missing in config.")

print("Please select the endpoint for the catalog")
for index, option in enumerate(endpoints): print(index, option)
selected = input("Endpoint: ")
for index, option in enumerate(endpoints):
    if int(selected) == index: 
        selectedEndpoint = endpoints[option]
        selectedEndpoint['endpointAPI'] = option
        break

def call(url,payload=None,runs=10):
    for run in range(runs):
        try:
            if payload:
                response = requests.post(url, headers=headers, data=json.dumps(payload))
            else:
                response = requests.get(url, headers=headers)
            if response.status_code == 200: return response
            print(f"Got {response.status_code} for {url} retrying...")
            print(json.dumps(response.json(), indent=4))
        except Exception as e:
            print(f"Failed to fetch {url} got error '{e}' retrying...")
        time.sleep(5)
    exit(f"Unable to fetch {url}")

headers = {'Accept': 'application/json','X-Ovh-Application':config['application_key'],'X-Ovh-Consumer':config['consumer_key'],
'Content-Type':'application/json;charset=utf-8','Host':selectedEndpoint['endpointAPI']}

print(f"Loading catalog from {selectedEndpoint['catalog']}")
catalogRaw = call(selectedEndpoint['catalog'])
catalog = catalogRaw.json()
catalogUnsorted = {}
for plan in catalog['plans']:
    for price in plan['pricings']:
        if "installation" in price['capacities']: continue
        if price['interval'] != 1: continue
        catalogUnsorted[plan['planCode']] = {"price":int(price['price']),"plan":plan}

catalogSorted = dict(sorted(catalogUnsorted.items(), key=lambda item: item[1]["price"]))

for index, (planCode,data) in enumerate(catalogSorted.items()):
    if not "product" in data['plan']: continue
    print(index, data['plan']['invoiceName'])
print("What plan do you want to buy? e.g 2 for KS-LE-B")

lookup = input()
planConfig = {}
for offerIndex, (planCode,data) in enumerate(catalogSorted.items()):
    if "product" in data['plan'] and offerIndex == int(lookup):
        planConfig['planCode'] = planCode
        for addon in data['plan']['addonFamilies']:
            if addon['mandatory'] != True: continue
            for index, option in enumerate(addon['addons']): print(index, option)
            print("Please select configuration")
            selected = input()
            for index, option in enumerate(addon['addons']):
                if int(selected) == index: planConfig[addon['name']] = option
        break

def datacenterToRegion(availableDataCenter):
    if availableDataCenter == "bhs": 
        return "canada"
    else:
        return "europe"

print("Loading availability...")
availabilityRaw = call(f'{selectedEndpoint["availability"]}?excludeDatacenters=false&planCode={planConfig["planCode"]}&server={planConfig["planCode"]}')
availability = availabilityRaw.json()
if not availability:
    print(f"Failed to fetch availability, please enter desired datacenter manualy.")
    dc = input()
else:
    for index, datacenter in enumerate(availability[0]['datacenters']):
        print(index, datacenter['datacenter'])
    selected = input()
    for index, datacenter in enumerate(availability[0]['datacenters']):
        if int(selected) == index: 
            dc = datacenter['datacenter']
            break

planConfig['region'] = datacenterToRegion(dc)
planConfig['datacenter'] = dc
print(f"Your selected config")
print(planConfig)
with open(f'{path}/plans/{planConfig['planCode']}-{planConfig['datacenter']}.json', 'w') as f: json.dump(planConfig, f, indent=4)
time.sleep(2)

# Instantiate. Visit https://api.ovh.com/createToken/?GET=/me
# to get your credentials
client = ovh.Client(
    endpoint=selectedEndpoint['endpoint'],
    application_key=config['application_key'],
    application_secret=config['application_secret'],
    consumer_key=config['consumer_key'],
)

# Print nice welcome message
print("Welcome", client.get('/me')['firstname'])
availableDataCenter = "bhs"
retry = 0

while True:
    print("Preparing Package")
    #getting current time
    print("Getting Time")
    response = call(f"https://{selectedEndpoint['endpointAPI']}/1.0/auth/time")
    timeDelta = int(response.text) - int(time.time())
    # creating a new cart
    cart = client.post("/order/cart", ovhSubsidiary=config['ovhSubsidiary'], _need_auth=False)
    #assign new cart to current user
    client.post("/order/cart/{0}/assign".format(cart.get("cartId")))
    #putting KS-A into cart
    #result = client.post(f'/order/cart/{cart.get("cartId")}/eco',{"duration":"P1M","planCode":"22sk010","pricingMode":"default","quantity":1})
    #apparently this shit sends malformed json whatever baguette
    payload = {'duration':'P1M','planCode':planConfig['planCode'],'pricingMode':'default','quantity':1}
    call(f"https://{selectedEndpoint['endpointAPI']}/1.0/order/cart/{cart.get('cartId')}/eco", payload)
    #getting current cart
    response = call(f"https://{selectedEndpoint['endpointAPI']}/1.0/order/cart/{cart.get('cartId')}")
    #modify item for checkout
    itemID = response.json()['items'][0]
    print(f'Getting current cart {cart.get("cartId")}')
    #set configurations
    configurations = [{'label':'region','value':planConfig['region']},{'label':'dedicated_datacenter','value':planConfig['datacenter']},{'label':'dedicated_os','value':'none_64.en'}]
    for entry in configurations:
        print(f"Setting {entry}")
        call(f"https://{selectedEndpoint['endpointAPI']}/1.0/order/cart/{cart.get('cartId')}/item/{itemID}/configuration",entry)
    #set options
    options = [{'itemId':itemID,'duration':'P1M','planCode':planConfig['bandwidth'],'pricingMode':'default','quantity':1},
            {'itemId':itemID,'duration':'P1M','planCode':planConfig['storage'],'pricingMode':'default','quantity':1},
            {'itemId':itemID,'duration':'P1M','planCode':planConfig['memory'],'pricingMode':'default','quantity':1}
    ]
    for option in options:
        print(f"Setting {option}")
        call(f"https://{selectedEndpoint['endpointAPI']}/1.0/order/cart/{cart.get('cartId')}/eco/options", option)
    print("Package ready, waiting for stock")
    #the order expires after about 1 day
    for check in range(70000):
        now = datetime.now()
        print(f'Run {check+1} {now.strftime("%H:%M:%S")}')
        #wait for stock
        try:
            response = requests.get(f'{selectedEndpoint["availability"]}?excludeDatacenters=false&planCode={planConfig["planCode"]}&server={planConfig["planCode"]}')
        except Exception as e:
            print(f"Failed to fetch stock got error '{e}' retrying...")
            time.sleep(2)
            continue
        if response.status_code == 200:
            stock = response.json()
            score = 0
            if not stock: 
                print(f"Unable to find {planConfig['planCode']} in availability.")
                time.sleep(randint(5,10))
                continue
            for datacenter in stock[0]['datacenters']:
                if datacenter['availability'] != "unavailable" and config['anyDatacenter']:
                    availableDataCenter = datacenter['datacenter'] 
                    score = score +1
                    break
                elif datacenter['availability'] != "unavailable" and datacenter['datacenter'] == config['dedicated_datacenter']:
                    availableDataCenter = datacenter['datacenter'] 
                    score = score +1
                    break
        else:
            time.sleep(randint(5,10))
            continue
        #lets checkout boooyaaa
        if score >= 1:
            #autopay should be set to true if you want automatic delivery, otherwise it will just generate a invoice
            payload={'autoPayWithPreferredPaymentMethod':config['autoPay'],'waiveRetractationPeriod':config['autoPay']}
            #prepare sig
            target = f"https://{selectedEndpoint['endpointAPI']}/1.0/order/cart/{cart.get('cartId')}/checkout"
            now = str(int(time.time()) + timeDelta)
            signature = hashlib.sha1()
            signature.update("+".join([config['application_secret'], config['consumer_key'],'POST', target, json.dumps(payload), now]).encode('utf-8'))
            headers['X-Ovh-Signature'] = "$1$" + signature.hexdigest()
            headers['X-Ovh-Timestamp'] = now
            try:
                response = requests.post(target, headers=headers, data=json.dumps(payload))
                if response.status_code == 200:
                    print(response.status_code)
                    print(json.dumps(response.json(), indent=4))
                    exit("Done")
                else:
                    print("Got non 200 response code on checkout, retrying")
                    print(json.dumps(response.json(), indent=4))
                    retry += 1
                    if retry > 15: exit()
                    if retry % 4 == 0 and config['switchRegion']:
                        print(f"Switching Region to {datacenterToRegion(availableDataCenter)} and datacenter to {availableDataCenter}") 
                        planConfig['datacenter'] = availableDataCenter
                        planConfig['region'] = datacenterToRegion(availableDataCenter)
                        break
            except Exception as e:
                print(f"Unable to submit order got '{e}' as error")
                retry += 1
                if retry > 15: exit()
            time.sleep(2)
        else:
            time.sleep(1)