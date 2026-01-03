# ---------------------------------------------------------------------------------- #
#                            Part of the X3r0Day project.                            #
#              You are free to use, modify, and redistribute this code,              #
#          provided proper credit is given to the original project X3r0Day.          #
# ---------------------------------------------------------------------------------- #

'''This script decodes the data from maps and create it into file'''




import os
import hashlib
import gc
from collections import deque
from multiprocessing import Pool, cpu_count
from nbt.nbt import NBTFile
from nbt.region import RegionFile
from rich.console import Console
from rich.progress import track


saveFolder = r"/home/cran/.local/share/PrismLauncher/instances/Meteor Main - 1.21.1/minecraft/saves/TestWorld"
startX, startY, startZ = 64, -60, 38

console = Console()

def line(text):
    console.print(text)

class WorldContext:
    def __init__(self, regionFolder):
        self.regionFolder = regionFolder
        self.openRegions = {}
        self.chunkCache = {}

    def getRegionFile(self, regionX, regionZ):
        key = (regionX, regionZ)
        if key not in self.openRegions:
            path = os.path.join(self.regionFolder, f"r.{regionX}.{regionZ}.mca")
            if not os.path.exists(path): return None
            self.openRegions[key] = RegionFile(path)
        return self.openRegions[key]

    def getChunk(self, globalChunkX, globalChunkZ):
        key = (globalChunkX, globalChunkZ)
        if key in self.chunkCache: return self.chunkCache[key]
        regionX = globalChunkX >> 5
        regionZ = globalChunkZ >> 5
        region = self.getRegionFile(regionX, regionZ)
        if not region: return None
        try:
            chunk = region.get_chunk(globalChunkX & 31, globalChunkZ & 31)
            self.chunkCache[key] = chunk
            return chunk
        except Exception: return None

    def close(self):
        for region in self.openRegions.values():
            try: region.close()
            except: pass
        self.openRegions.clear()
        self.chunkCache.clear()

def find3dCluster(world, startX, startY, startZ):
    found = []
    visited = set()
    queue = deque([(startX, startY, startZ)])

    while queue:
        x, y, z = queue.popleft()
        if (x, y, z) in visited: continue
        visited.add((x, y, z))

        chunk = world.getChunk(x >> 4, z >> 4)
        if not chunk: continue

        tileEntities = chunk.get("block_entities") or chunk.get("Level", {}).get("TileEntities") or chunk.get("TileEntities")
        if not tileEntities: continue

        for te in tileEntities:
            if te["x"].value == x and te["y"].value == y and te["z"].value == z and "id" in te and "chest" in te["id"].value.lower():
                found.append(te)
                for n in [(x+1,y,z),(x-1,y,z),(x,y+1,z),(x,y-1,z),(x,y,z+1),(x,y,z-1)]:
                    if n not in visited: queue.append(n)
                break
    return found

def _readWorker(mapIds):
    dataDir = os.path.join(saveFolder, "data")
    results = []
    for mapId in mapIds:
        try:
            nbt = NBTFile(os.path.join(dataDir, f"map_{mapId}.dat"))
            if "data" in nbt:
                results.append(nbt["data"]["colors"].value)
            else:
                results.append(b"")
        except Exception:
            results.append(b"")
    return results

def retrieve():
    worldName = os.path.basename(saveFolder)
    line(f"extracting from {worldName} ({startX}, {startY}, {startZ})\n")

    world = WorldContext(os.path.join(saveFolder, "region"))

    try:
        chests = find3dCluster(world, startX, startY, startZ)
        if not chests:
            line("scan: no connected chests found")
            return

        mapList = [] 
        totalFileSize = 0
        originalFilename = "unknown_file"

        # 1. Scan Metadata
        for chest in chests:
            if "Items" not in chest: continue
            
            for shulkerItem in chest["Items"]:
                
                if totalFileSize == 0 and "components" in shulkerItem:
                    comps = shulkerItem["components"]
                    if "minecraft:custom_data" in comps:
                        customData = comps["minecraft:custom_data"]
                        if "file_size" in customData:
                            totalFileSize = customData["file_size"].value
                        if "filename" in customData:
                            originalFilename = customData["filename"].value

                if "components" in shulkerItem and "minecraft:container" in shulkerItem["components"]:
                    container = shulkerItem["components"]["minecraft:container"]
                    
                    for entry in container:
                        item = entry["item"]
                        if "components" in item:
                            iComps = item["components"]
                            
                            seqId = -1
                            if "minecraft:custom_data" in iComps and "seq_id" in iComps["minecraft:custom_data"]:
                                seqId = iComps["minecraft:custom_data"]["seq_id"].value
                            
                            if seqId != -1 and "minecraft:map_id" in iComps:
                                mapId = iComps["minecraft:map_id"].value
                                mapList.append((seqId, mapId))
            
        line(f"scan: {len(chests)} chests found")

        mapList.sort(key=lambda x: x[0])
        mapIds = [x[1] for x in mapList]

        if totalFileSize > 0:
            mb = totalFileSize / 1024 / 1024
            line(f"index: {len(mapIds)} map fragments")
            line(f"file : {originalFilename} ({mb:.1f} MB expected)\n")
        else:
            line(f"index: {len(mapIds)} map fragments")
            line(f"file : {originalFilename} (unknown size)\n")

        line("reading maps…")
        
        # --- So we'll batch the maps 5k at a time to avoid OOM (Out of Memory) Error ---
        # 5000 Maps * 16KB = ~80MB RAM usage per batch.
        RAM_BATCH_SIZE = 5000 
        WORKER_CHUNK_SIZE = 100 # <- No. of maps one CPU core processes at a time

        with open(originalFilename, "wb") as f:
            hasher = hashlib.md5()
            bytesWritten = 0
            
            totalBatches = (len(mapIds) + RAM_BATCH_SIZE - 1) // RAM_BATCH_SIZE
            
            with Pool(cpu_count()) as pool:
                for i in track(range(0, len(mapIds), RAM_BATCH_SIZE), description="processing", total=totalBatches):
                    
                    batchIds = mapIds[i : i + RAM_BATCH_SIZE]
                    

                    workerTasks = []
                    for j in range(0, len(batchIds), WORKER_CHUNK_SIZE):
                        workerTasks.append(batchIds[j : j + WORKER_CHUNK_SIZE])

                    batchResults = pool.map(_readWorker, workerTasks)
                    
                    for chunkList in batchResults:
                        for chunk in chunkList:
                            if not chunk: continue
                            
                            if totalFileSize > 0:
                                remaining = totalFileSize - bytesWritten
                                if remaining <= 0: break
                                if len(chunk) > remaining:
                                    chunk = chunk[:remaining]
                            
                            f.write(chunk)
                            hasher.update(chunk)
                            bytesWritten += len(chunk)
                    
                    del batchResults
                    del workerTasks
                    gc.collect()

        finalHash = hasher.hexdigest().upper()

        line(f"\nwritten {bytesWritten:,} bytes")
        line(f"md5 {finalHash}\n")
        line("done")

    finally:
        world.close()

if __name__ == "__main__":
    retrieve()