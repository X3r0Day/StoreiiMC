# ---------------------------------------------------------------------------------- #
#                            Part of the X3r0Day project.                            #
#              You are free to use, modify, and redistribute this code,              #
#          provided proper credit is given to the original project X3r0Day.          #
# ---------------------------------------------------------------------------------- #


#######################################################################################################################
# - THIS VERSION IS INTENDED TO WORK ON 1.21 VERSION, YOU CAN CHANGE VERSION BY EDITING "dataVersion"L:39 VARIABLE    #
# - Data is stored as noise maps in MAPS in minecraft, which can be decoded back to original file!                    #
#######################################################################################################################


'''This script will encode and build map to store in minecraft!'''



import os
import math
import hashlib
import random
from collections import deque
from multiprocessing import Pool, cpu_count
from nbt.nbt import (
    NBTFile,
    TAG_Compound,
    TAG_Byte,
    TAG_Int,
    TAG_Long,
    TAG_Byte_Array,
    TAG_String,
    TAG_List
)
from nbt.region import RegionFile
from rich.console import Console
from rich.progress import track

saveFolder = r"/home/cran/.local/share/PrismLauncher/instances/Meteor Main - 1.21.1/minecraft/saves/TestWorld"
startX, startY, startZ = 64, -60, 38
inputFile = "/home/cran/Documents/Projects/RAG/StoreiiMC/10gb_zeros.bin"
startMapId = 50000
dataVersion = 3955 # 1.21.x

console = Console()

def line(text):
    console.print(text)

class WorldContext:
    def __init__(self, regionFolder):
        self.regionFolder = regionFolder
        self.openRegions = {}
        self.chunkCache = {}
        self.modifiedChunks = set()

    def getRegionFile(self, regionX, regionZ):
        key = (regionX, regionZ)
        if key not in self.openRegions:
            path = os.path.join(self.regionFolder, f"r.{regionX}.{regionZ}.mca")
            if not os.path.exists(path):
                return None
            self.openRegions[key] = RegionFile(path)
        return self.openRegions[key]

    def getChunk(self, globalChunkX, globalChunkZ):
        key = (globalChunkX, globalChunkZ)
        if key in self.chunkCache:
            return self.chunkCache[key]

        regionX = globalChunkX >> 5
        regionZ = globalChunkZ >> 5
        region = self.getRegionFile(regionX, regionZ)
        if not region:
            return None

        try:
            chunk = region.get_chunk(globalChunkX & 31, globalChunkZ & 31)
            self.chunkCache[key] = chunk
            return chunk
        except Exception:
            return None

    def markDirty(self, globalChunkX, globalChunkZ):
        self.modifiedChunks.add((globalChunkX, globalChunkZ))

    def saveAll(self):
        for globalChunkX, globalChunkZ in self.modifiedChunks:
            regionX = globalChunkX >> 5
            regionZ = globalChunkZ >> 5
            chunk = self.chunkCache.get((globalChunkX, globalChunkZ))
            if chunk:
                self.openRegions[(regionX, regionZ)].write_chunk(
                    globalChunkX & 31, globalChunkZ & 31, chunk
                )
        for region in self.openRegions.values():
            region.close()

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

        tileEntities = (
            chunk.get("block_entities")
            or chunk.get("Level", {}).get("TileEntities")
            or chunk.get("TileEntities")
        )

        if not tileEntities: continue

        for te in tileEntities:
            if (
                te["x"].value == x
                and te["y"].value == y
                and te["z"].value == z
                and "id" in te
                and "chest" in te["id"].value.lower()
            ):
                te.globalChunkCoords = (x >> 4, z >> 4)
                found.append(te)
                for n in [(x+1,y,z),(x-1,y,z),(x,y+1,z),(x,y-1,z),(x,y,z+1),(x,y,z-1)]:
                    if n not in visited: queue.append(n)
                break

    found.sort(key=lambda t: (t["y"].value, t["x"].value, t["z"].value))
    return found

def createMapFile(mapId, byteData):
    if len(byteData) < 16384:
        byteData += b"\x00" * (16384 - len(byteData))

    nbt = NBTFile()
    nbt.tags.append(TAG_Int(name="DataVersion", value=dataVersion))

    data = TAG_Compound(name="data")
    data.tags.extend([
        TAG_Byte(name="scale", value=0),
        TAG_Byte(name="dimension", value=0),
        TAG_Byte(name="locked", value=1),
        TAG_Byte(name="tracking_position", value=0),
        TAG_Byte(name="unlimited_tracking", value=0),
        TAG_Int(name="xCenter", value=0),
        TAG_Int(name="zCenter", value=0),
    ])

    colors = TAG_Byte_Array(name="colors")
    colors.value = byteData
    data.tags.append(colors)
    nbt.tags.append(data)

    path = os.path.join(saveFolder, "data", f"map_{mapId}.dat")
    nbt.write_file(path)

def _mapWorker(batch):
    for args in batch:
        createMapFile(*args)

def _fileChunkGenerator(filePath, startId, chunkSize, batchSize=1000):
    readSize = chunkSize * batchSize
    with open(filePath, "rb") as f:
        idx = 0
        while True:
            buffer = f.read(readSize)
            if not buffer: break
            
            batch = []
            for i in range(0, len(buffer), chunkSize):
                batch.append((startId + idx, buffer[i : i + chunkSize]))
                idx += 1
            
            yield batch

def inject():
    worldName = os.path.basename(saveFolder)
    line(f"injecting {inputFile} into {worldName} @ ({startX}, {startY}, {startZ})\n")

    if not os.path.exists(inputFile):
        line("input file not found")
        return

    fileSize = os.path.getsize(inputFile)

    hasher = hashlib.md5()
    with open(inputFile, "rb") as f:
        while chunk := f.read(8192 * 1024):
            hasher.update(chunk)
    fileHash = hasher.hexdigest().upper()

    line(f"file size {fileSize:,} bytes")
    line(f"md5 {fileHash}\n")

    bytesPerMap = 16384
    totalMaps = math.ceil(fileSize / bytesPerMap)
    batchSize = 1000
    totalBatches = math.ceil(totalMaps / batchSize)

    dataDir = os.path.join(saveFolder, "data")
    os.makedirs(dataDir, exist_ok=True)

    line(f"building {totalMaps} map files (optimized)")
    
    with Pool(cpu_count()) as pool:
        generator = _fileChunkGenerator(inputFile, startMapId, bytesPerMap, batchSize)
        for _ in track(pool.imap_unordered(_mapWorker, generator), total=totalBatches, description="batches"):
            pass

    world = WorldContext(os.path.join(saveFolder, "region"))
    chests = find3dCluster(world, startX, startY, startZ)

    if not chests:
        line("\nno chests found at start position")
        return

    capacity = len(chests) * 729 * bytesPerMap
    line(f"\nscan: {len(chests)} chests found")
    line(f"capacity: {capacity / 1024 / 1024:.2f} MB")

    if capacity < fileSize:
        missing = fileSize - capacity
        needed = math.ceil(missing / bytesPerMap / 729)
        line(f"insufficient capacity (need {needed} more chests)")
        return

    currMap = 0
    shulkerColors = ["minecraft:black_shulker_box","minecraft:gray_shulker_box","minecraft:light_gray_shulker_box","minecraft:cyan_shulker_box"]

    line("\nwriting maps into chests")
    for chestIndex, chest in enumerate(chests):
        if currMap >= totalMaps: break

        gcx, gcz = chest.globalChunkCoords
        world.markDirty(gcx, gcz)

        chest["CustomName"] = TAG_String(f'{{"text":"NODE_{chestIndex:03d}","color":"aqua","bold":true}}')

        if "Items" in chest: del chest["Items"]
        chestItems = TAG_List(name="Items", type=TAG_Compound)

        for chestSlot in range(27):
            if currMap >= totalMaps: break

            shulker = TAG_Compound()
            shulker["id"] = TAG_String(shulkerColors[(chestIndex + chestSlot) % len(shulkerColors)])
            shulker["Count"] = TAG_Byte(1)
            shulker["Slot"] = TAG_Byte(chestSlot)

            container = TAG_List(name="minecraft:container", type=TAG_Compound)

            for slot in range(27):
                if currMap >= totalMaps: break

                mapId = startMapId + currMap
                mapItem = TAG_Compound()
                mapItem["id"] = TAG_String("minecraft:filled_map")
                mapItem["count"] = TAG_Int(1)

                comps = TAG_Compound()
                comps["minecraft:map_id"] = TAG_Int(mapId)
                comps["minecraft:custom_name"] = TAG_String(f'{{"text":"{random.choice(["0x","1x"])}{random.randint(10,99)}","obfuscated":true}}')
                
                customData = TAG_Compound()
                customData["seq_id"] = TAG_Int(currMap)
                comps["minecraft:custom_data"] = customData
                
                mapItem["components"] = comps

                entry = TAG_Compound()
                entry["slot"] = TAG_Int(slot)
                entry["item"] = mapItem
                container.append(entry)

                currMap += 1

            shulkerComps = TAG_Compound(name="components")
            shulkerComps["minecraft:container"] = container
            shulkerComps["minecraft:custom_name"] = TAG_String(f'{{"text":"SECTOR_{chestIndex}-{chestSlot}","color":"green"}}')

            if chestIndex == 0 and chestSlot == 0:
                metaData = TAG_Compound()
                metaData["file_size"] = TAG_Long(fileSize)
                metaData["filename"] = TAG_String(os.path.basename(inputFile))
                shulkerComps["minecraft:custom_data"] = metaData

            shulker["components"] = shulkerComps
            chestItems.append(shulker)

        chest.tags.append(chestItems)

    line("\nfinalizing")
    world.saveAll()
    line("done")

if __name__ == "__main__":
    inject()
