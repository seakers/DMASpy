import json
import requests
import sys
import time
import argparse
import re
import threading
import datetime

from landsatxplore.api import API
from landsatxplore.earthexplorer import EarthExplorer

# Initialize a new API instance and get an access key
api = API("bgorr", "SpectralAnalysis8")
fn = ''
path = "./scenarios/sim_test/imagery/" # Fill a valid download path
maxthreads = 5 # Threads count for downloads
sema = threading.Semaphore(value=maxthreads)
label = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") # Customized label using date time
threads = []
# The entityIds/displayIds need to save to a text file such as scenes.txt.
# The header of text file should follow the format: datasetName|displayId or datasetName|entityId. 
# sample file - scenes.txt
# landsat_ot_c2_l2|displayId
# LC08_L2SP_012025_20201231_20210308_02_T1
# LC08_L2SP_012027_20201215_20210314_02_T1
scenesFile = './scenarios/sim_test/imagery/scenes.txt'

# Send http request
def sendRequest(url, data, apiKey = None, exitIfNoResponse = True):  
    json_data = json.dumps(data)
    
    if apiKey == None:
        response = requests.post(url, json_data)
    else:
        headers = {'X-Auth-Token': apiKey}              
        response = requests.post(url, json_data, headers = headers)  
    
    try:
      httpStatusCode = response.status_code 
      if response == None:
          print("No output from service")
          if exitIfNoResponse: sys.exit()
          else: return False
      output = json.loads(response.text)
      if output['errorCode'] != None:
          print(output['errorCode'], "- ", output['errorMessage'])
          if exitIfNoResponse: sys.exit()
          else: return False
      if  httpStatusCode == 404:
          print("404 Not Found")
          if exitIfNoResponse: sys.exit()
          else: return False
      elif httpStatusCode == 401: 
          print("401 Unauthorized")
          if exitIfNoResponse: sys.exit()
          else: return False
      elif httpStatusCode == 400:
          print("Error Code", httpStatusCode)
          if exitIfNoResponse: sys.exit()
          else: return False
    except Exception as e: 
          response.close()
          print(e)
          if exitIfNoResponse: sys.exit()
          else: return False
    response.close()
    
    return output['data']

def downloadFile(url):
    sema.acquire()
    try:        
        response = requests.get(url, stream=True)
        disposition = response.headers['content-disposition']
        filename = re.findall("filename=(.+)", disposition)[0].strip("\"")
        fn = filename
        print(f"Downloading {filename} ...\n")
        if path != "" and path[-1] != "/":
            filename = "/" + filename
        open(path+filename, 'wb').write(response.content)
        print(f"Downloaded {filename}\n")
        sema.release()
    except Exception as e:
        print(f"Failed to download from {url}. Will try to re-download.")
        sema.release()
        runDownload(threads, url)
    
def runDownload(threads, url):
    thread = threading.Thread(target=downloadFile, args=(url,))
    threads.append(thread)
    thread.start()

def getLandsatFilePath(lat,lon):
    username = "bgorr"
    password = "SpectralAnalysis8"
    filetype = "band"

    # Search for Landsat TM scenes
    scenes = api.search(
        dataset='landsat_ot_c2_l2',
        latitude=lat,
        longitude= lon,
        start_date='2020-01-01',
        end_date='2020-12-01',
        max_cloud_cover=10
    )
    print(scenes)

    # for scene in scenes:
    #     print(scene['display_id'])
    scene = scenes[0]
    with open(scenesFile, 'w') as f:
        f.write('landsat_ot_c2_l2|displayId\n')
        f.write(scene['display_id'])
    print("\nRunning Scripts...\n")
    startTime = time.time()
    
    serviceUrl = "https://m2m.cr.usgs.gov/api/api/json/stable/"
    
    # Login
    payload = {'username' : username, 'password' : password}    
    apiKey = sendRequest(serviceUrl + "login", payload)    
    print("API Key: " + apiKey + "\n")
    
    # Read scenes
    f = open(scenesFile, "r")
    lines = f.readlines()   
    f.close()
    header = lines[0].strip()
    datasetName = header[:header.find("|")]
    idField = header[header.find("|")+1:]
    
    print("Scenes details:")
    print(f"Dataset name: {datasetName}")
    print(f"Id field: {idField}\n")

    entityIds = []
    
    lines.pop(0)
    for line in lines:        
        entityIds.append(line.strip())

    # Search scenes 
    # If you don't have a scenes text file that you can use scene-search to identify scenes you're interested in
    # https://m2m.cr.usgs.gov/api/docs/reference/#scene-search
    # payload = { 
    #             'datasetName' : '', # dataset alias
    #             'maxResults' : 10, # max results to return
    #             'startingNumber' : 1, 
    #             'sceneFilter' : {} # scene filter
    #           }
    
    # results = sendRequest(serviceUrl + "scene-search", payload, apiKey)  
    # for result in results:
    #     entityIds.append(result['entityId'])
    
    # Add scenes to a list
    listId = f"temp_{datasetName}_list" # customized list id
    payload = {
        "listId": listId,
        'idField' : idField,
        "entityIds": entityIds,
        "datasetName": datasetName
    }
    
    print("Adding scenes to list...\n")
    count = sendRequest(serviceUrl + "scene-list-add", payload, apiKey)    
    print("Added", count, "scenes\n")

    # Get download options
    payload = {
        "listId": listId,
        "datasetName": datasetName
    }
      
    print("Getting product download options...\n")
    products = sendRequest(serviceUrl + "download-options", payload, apiKey)
    print("Got product download options\n")
    
    # Select products
    downloads = []
    if filetype == 'bundle':
        # select bundle files
        for product in products:        
            if product["bulkAvailable"]:               
                downloads.append({"entityId":product["entityId"], "productId":product["id"]})
    elif filetype == 'band':
        # select band files
        for product in products:  
            if product["secondaryDownloads"] is not None and len(product["secondaryDownloads"]) > 0:
                for secondaryDownload in product["secondaryDownloads"]:
                    if secondaryDownload["bulkAvailable"]:
                        downloads.append({"entityId":secondaryDownload["entityId"], "productId":secondaryDownload["id"]})
    else:
        # select all available files
        for product in products:        
            if product["bulkAvailable"]:               
                downloads.append({"entityId":product["entityId"], "productId":product["id"]})
                if product["secondaryDownloads"] is not None and len(product["secondaryDownloads"]) > 0:
                    for secondaryDownload in product["secondaryDownloads"]:
                        if secondaryDownload["bulkAvailable"]:
                            downloads.append({"entityId":secondaryDownload["entityId"], "productId":secondaryDownload["id"]})
    
    # Remove the list
    payload = {
        "listId": listId
    }
    sendRequest(serviceUrl + "scene-list-remove", payload, apiKey)                
    
    # Send download-request
    payLoad = {
        "downloads": downloads,
        "label": label,
        'returnAvailable': True
    }
    
    print(f"Sending download request ...\n")
    results = sendRequest(serviceUrl + "download-request", payLoad, apiKey)
    print(f"Done sending download request\n") 

      
    for result in results['availableDownloads']:       
        print(f"Get download url: {result['url']}\n" )
        runDownload(threads, result['url'])

    preparingDownloadCount = len(results['preparingDownloads'])
    preparingDownloadIds = []
    if preparingDownloadCount > 0:
        for result in results['preparingDownloads']:  
            preparingDownloadIds.append(result['downloadId'])
  
        payload = {"label" : label}                
        # Retrieve download urls
        print("Retrieving download urls...\n")
        results = sendRequest(serviceUrl + "download-retrieve", payload, apiKey, False)
        if results != False:
            for result in results['available']:
                if result['downloadId'] in preparingDownloadIds:
                    preparingDownloadIds.remove(result['downloadId'])
                    print(f"Get download url: {result['url']}\n" )
                    runDownload(threads, result['url'])
                
            for result in results['requested']:   
                if result['downloadId'] in preparingDownloadIds:
                    preparingDownloadIds.remove(result['downloadId'])
                    print(f"Get download url: {result['url']}\n" )
                    runDownload(threads, result['url'])
        
        # Don't get all download urls, retrieve again after 30 seconds
        while len(preparingDownloadIds) > 0: 
            print(f"{len(preparingDownloadIds)} downloads are not available yet. Waiting for 30s to retrieve again\n")
            time.sleep(30)
            results = sendRequest(serviceUrl + "download-retrieve", payload, apiKey, False)
            if results != False:
                for result in results['available']:                            
                    if result['downloadId'] in preparingDownloadIds:
                        preparingDownloadIds.remove(result['downloadId'])
                        print(f"Get download url: {result['url']}\n" )
                        runDownload(threads, result['url'])
    
    print("\nGot download urls for all downloads\n")                
    # Logout
    endpoint = "logout"  
    if sendRequest(serviceUrl + endpoint, None, apiKey) == None:        
        print("Logged Out\n")
    else:
        print("Logout Failed\n")  
     
    print("Downloading files... Please do not close the program\n")
    for thread in threads:
        thread.join()
            
    print("Complete Downloading")
    
    executionTime = round((time.time() - startTime), 2)
    print(f'Total time: {executionTime} seconds')
    return fn