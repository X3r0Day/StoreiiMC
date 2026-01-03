# ---------------------------------------------------------------------------------- #
#                            Part of the X3r0Day project.                            #
#              You are free to use, modify, and redistribute this code,              #
#          provided proper credit is given to the original project X3r0Day.          #
# ---------------------------------------------------------------------------------- #

'''!! This script will delete all of the data from chests !!'''




import os
from collections import deque
from nbt.nbt import TAG_String
from nbt.region import RegionFile
from rich.console import Console
from rich.progress import track


saveFolder = r"/home/cran/.local/share/PrismLauncher/instances/Meteor Main - 1.21.1/minecraft/saves/TestWorld"
startX, startY, startZ = 32, -60, -5

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

def delete():
    worldName = os.path.basename(saveFolder)
    line(f"formatting drive in {worldName} @ ({startX}, {startY}, {startZ})\n")

    world = WorldContext(os.path.join(saveFolder, "region"))
    chests = find3dCluster(world, startX, startY, startZ)

    if not chests:
        line("\nno chests found at start position")
        return

    line(f"found {len(chests)} nodes connected")
    
    console.print("\n[bold red]WARNING: THIS WILL PERMANENTLY ERASE ALL DATA IN THE CLUSTER[/bold red]")
    if console.input("[bold red]TYPE 'YES' TO CONFIRM: [/bold red]").strip().upper() != "YES":
        line("aborted")
        return

    line("\nclearing data...")

    cleanedCount = 0
    for chest in track(chests, description="formatting"):
        gcx, gcz = chest.globalChunkCoords
        
        hasItems = "Items" in chest
        hasName = "CustomName" in chest

        if hasItems or hasName:
            world.markDirty(gcx, gcz)
            if hasItems: del chest["Items"]
            if hasName: del chest["CustomName"]
            cleanedCount += 1

    line(f"\nformatted {cleanedCount} chests")
    
    line("finalizing")
    world.saveAll()
    line("done")

if __name__ == "__main__":
    delete()