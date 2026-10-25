import pygame
import math
import random
import colorsys
import argparse
from array import array
from collections import deque
from functools import lru_cache
from pathlib import Path

parser = argparse.ArgumentParser(description="Raycasting maze game")
parser.add_argument(
    "--print-map", "--print", nargs="?", const="world_map.png", metavar="PNG",
    help="save a PNG of the full 512x512 world grid (default: world_map.png)",
)
parser.add_argument(
    "--print-sprites", nargs="?", const="sprites.png", metavar="PNG",
    help="save a labeled PNG contact sheet of the game's sprites (default: sprites.png)",
)
parser.add_argument(
    "--super-resolution", action="store_true",
    help="export the full map at 8 pixels per world block (4096x4096)",
)
parser.add_argument("--seed", type=int, help="set the world seed for a reproducible map or game")
parser.add_argument("--debug", action="store_true",
                    help="enable debug keys including M to teleport to the boss room")
args = parser.parse_args()

# Initialize Pygame
pygame.mixer.pre_init(22050, -16, 1, 1024)
pygame.init()


def make_window_icon():
    """Draw a chunky pink friendly orb for the game window icon."""
    pixels = (
        "................",
        "......KKKK......",
        "....KKPPPPKK....",
        "...KPPPPPPPPK...",
        "..KPPPPPPPPPPK..",
        ".KPPPPPPPPPPPPK.",
        ".KPPWPPPPPPPPPK.",
        "KPPPLPPPPPPPPPPK",
        "KPPPPPPPPPPPPPPK",
        "KPPPPPPPPPPPPPPK",
        ".KPPPPPPPPPPPPK.",
        ".KPPPPPPPPPPPK..",
        "..KPPPPPPPPPK...",
        "...KKPPPPPKK....",
        "......KKKK......",
        "................",
    )
    colors = {
        "K": (55, 18, 54),
        "P": (255, 100, 190),
        "L": (255, 175, 220),
        "W": (255, 245, 255),
    }
    icon = pygame.Surface((64, 64), pygame.SRCALPHA)
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            if pixel in colors:
                pygame.draw.rect(icon, colors[pixel], (x * 4, y * 4, 4, 4))
    return icon


if args.print_map is not None or args.print_sprites is not None:
    WIDTH, HEIGHT = 1000, 1000
    screen = pygame.Surface((WIDTH, HEIGHT))
else:
    screen = pygame.display.set_mode(
        (640, 480), pygame.FULLSCREEN | pygame.SCALED, vsync=1
    )
    pygame.display.set_icon(make_window_icon())
    pygame.mouse.set_visible(False)
    WIDTH, HEIGHT = screen.get_size()
floor_grid_layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
boss_glass_layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
clock = pygame.time.Clock()
screen_grain = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

@lru_cache(maxsize=64)
def make_floor_reflection_gradient(strength_step, tint=(205, 165, 255)):
    """Build a soft radial glow once per quantized reflection strength."""
    size = (96, 48)
    gradient = pygame.Surface(size, pygame.SRCALPHA)
    strength = strength_step / 10.0
    center_x, center_y = (size[0] - 1) / 2, (size[1] - 1) / 2
    for y in range(size[1]):
        for x in range(size[0]):
            nx = (x - center_x) / center_x
            ny = (y - center_y) / center_y
            radius_sq = nx * nx + ny * ny
            if radius_sq >= 1.0:
                continue
            falloff = (1.0 - radius_sq) ** 1.5
            center_mix = (1.0 - math.sqrt(radius_sq)) ** 0.7
            if tint == (205, 165, 255):
                red = int(145 + (245 - 145) * center_mix)
                green = int(75 + (220 - 75) * center_mix)
                blue = int(235 + (255 - 235) * center_mix)
            else:
                outer = tuple(int(channel * 0.58) for channel in tint)
                center = tuple(int(channel * 0.75 + 255 * 0.25) for channel in tint)
                red, green, blue = tuple(
                    int(out * (1.0 - center_mix) + inner * center_mix)
                    for out, inner in zip(outer, center)
                )
            alpha = min(220, int(65 * strength * falloff))
            gradient.set_at((x, y), (red, green, blue, alpha))
    return gradient


def draw_floor_reflection(target, screen_x, floor_y, depth, strength, wall_depths,
                          tint=(205, 165, 255), noise_density=1.0):
    """Draw a soft, perspective-scaled plasma glow onto the visible floor."""
    if depth <= 1:
        return
    radius_x = max(3, min(WIDTH // 2, int(58 * DIST_PLANE / depth)))
    radius_y = max(3, min(34, int(8 * DIST_PLANE / depth)))
    strength_step = max(1, int(round(strength * 10)))
    glow = pygame.transform.smoothscale(
        make_floor_reflection_gradient(strength_step, tint),
        (radius_x * 2, radius_y * 2),
    )

    # Increase the static with the light strength so bright explosions keep
    # their edges noisy instead of exposing the layered ellipse shapes.
    noise_scale = max(1.0, strength / 0.9)
    for _ in range(int(150 * noise_scale * noise_density)):
        noise_x = random.randrange(radius_x * 2)
        noise_y = random.randrange(radius_y * 2)
        nx = (noise_x - radius_x) / radius_x
        ny = (noise_y - radius_y) / radius_y
        if nx * nx + ny * ny > 1 or random.random() < 0.12:
            continue
        if tint == (205, 165, 255):
            noise_color = random.choice(((220, 205, 255), (170, 115, 255),
                                         (255, 255, 255), (130, 70, 220)))
        else:
            bright_tint = tuple(int(channel * 0.75 + 255 * 0.25) for channel in tint)
            dark_tint = tuple(int(channel * 0.6) for channel in tint)
            noise_color = random.choice((tint, bright_tint, (255, 255, 255), dark_tint))
        alpha = min(200, int(random.randint(24, 88) * noise_scale))
        pygame.draw.line(glow, (*noise_color, alpha), (noise_x, noise_y), (noise_x, noise_y))

    left = int(screen_x) - radius_x
    top = int(floor_y) - radius_y
    visible_top = max(int(HEIGHT / 2), top, 0)
    visible_bottom = min(HEIGHT, top + radius_y * 2)
    if visible_top >= visible_bottom:
        return
    source_y = visible_top - top
    for x in range(max(0, left), min(WIDTH, left + radius_x * 2)):
        if depth >= wall_depths[x]:
            continue
        source_x = x - left
        glow_column = glow.subsurface((source_x, source_y, 1, visible_bottom - visible_top))
        target.blit(glow_column, (x, visible_top))


@lru_cache(maxsize=256)
def make_enemy_floor_gradient(color):
    """Build a faint, soft floor glow in an enemy's color."""
    size = (96, 48)
    gradient = pygame.Surface(size, pygame.SRCALPHA)
    center_x, center_y = (size[0] - 1) / 2, (size[1] - 1) / 2
    for y in range(size[1]):
        for x in range(size[0]):
            nx = (x - center_x) / center_x
            ny = (y - center_y) / center_y
            radius_sq = nx * nx + ny * ny
            if radius_sq >= 1.0:
                continue
            falloff = (1.0 - radius_sq) ** 1.7
            center_mix = (1.0 - math.sqrt(radius_sq)) * 0.35
            glow_color = tuple(
                min(255, int(channel + (255 - channel) * center_mix))
                for channel in color
            )
            alpha = int(30 * falloff)
            gradient.set_at((x, y), (*glow_color, alpha))
    return gradient


def draw_enemy_floor_glow(target, enemy, wall_depths, player_x, player_y, player_angle):
    """Project a subtle, persistent enemy-colored glow onto visible floor."""
    dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
    distance = math.hypot(dx, dy)
    relative = (math.atan2(dy, dx) - player_angle + math.pi) % math.tau - math.pi
    depth = distance * math.cos(relative)
    if (depth <= 1 or distance > VIEW_DISTANCE_BLOCKS * TILE_SIZE
            or abs(relative) > HALF_FOV):
        return

    screen_x = (relative + HALF_FOV) / STEP_ANGLE
    floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / depth
    radius_x = max(2, min(WIDTH // 3, int(24 * DIST_PLANE / depth)))
    radius_y = max(2, min(18, int(3.5 * DIST_PLANE / depth)))
    glow = pygame.transform.smoothscale(
        make_enemy_floor_gradient(enemy["color"]), (radius_x * 2, radius_y * 2)
    )

    left = int(screen_x) - radius_x
    top = int(floor_y) - radius_y
    visible_top = max(int(HEIGHT / 2), top, 0)
    visible_bottom = min(HEIGHT, top + radius_y * 2)
    if visible_top >= visible_bottom:
        return
    source_y = visible_top - top
    for x in range(max(0, left), min(WIDTH, left + radius_x * 2)):
        if depth >= wall_depths[x]:
            continue
        glow_column = glow.subsurface((x - left, source_y, 1, visible_bottom - visible_top))
        target.blit(glow_column, (x, visible_top))

TILE_SIZE = 64
VIEW_DISTANCE_BLOCKS = 20
VICTORY_MUSIC_TEMPO = 142
CHUNK_SIZE = 32
WORLD_GRID_BLOCKS = 512
WORLD_FIELD_BLOCKS = 64
WORLD_CHUNKS_PER_SIDE = WORLD_GRID_BLOCKS // CHUNK_SIZE
WORLD_CENTER_BLOCK = WORLD_GRID_BLOCKS / 2
WORLD_CENTER_WORLD = WORLD_CENTER_BLOCK * TILE_SIZE
BOSS_ROOM_SIZE = 16
BOSS_ROOM_LEFT = int(WORLD_CENTER_BLOCK) - BOSS_ROOM_SIZE // 2
BOSS_ROOM_TOP = int(WORLD_CENTER_BLOCK) - BOSS_ROOM_SIZE // 2
BOSS_ROOM_RIGHT = BOSS_ROOM_LEFT + BOSS_ROOM_SIZE - 1
BOSS_ROOM_BOTTOM = BOSS_ROOM_TOP + BOSS_ROOM_SIZE - 1
BOSS_CORE_LEFT = int(WORLD_CENTER_BLOCK) - 1
BOSS_CORE_TOP = int(WORLD_CENTER_BLOCK) - 1
BOSS_EXIT_DOORS = (
    (int(WORLD_CENTER_BLOCK) - 1, BOSS_ROOM_TOP),
    (BOSS_ROOM_RIGHT, int(WORLD_CENTER_BLOCK)),
    (int(WORLD_CENTER_BLOCK), BOSS_ROOM_BOTTOM),
    (BOSS_ROOM_LEFT, int(WORLD_CENTER_BLOCK) - 1),
)
BOSS_EXIT_DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))
BOSS_EXIT_COLOR = (255, 34, 48)
BOSS_ESCAPE_DOOR = BOSS_EXIT_DOORS[0]
BOSS_ESCAPE_DIRECTION = BOSS_EXIT_DIRECTIONS[0]
BOSS_ESCAPE_CORRIDOR_LENGTH = 36
BOSS_ESCAPE_FRAME_COLOR = (150, 225, 255)
BOSS_ESCAPE_PORTAL_CELL = (
    BOSS_ESCAPE_DOOR[0] + BOSS_ESCAPE_DIRECTION[0] * (BOSS_ESCAPE_CORRIDOR_LENGTH + 1),
    BOSS_ESCAPE_DOOR[1] + BOSS_ESCAPE_DIRECTION[1] * (BOSS_ESCAPE_CORRIDOR_LENGTH + 1),
)
BOSS_NAME = "RECTANGULUS"
BOSS_MAX_HEALTH = 50
MAZE_NODES_PER_SIDE = 5
MAZE_NODE_SPACING = 6
WORLD_MASK = (1 << 64) - 1
WORLD_SEED = (args.seed & WORLD_MASK) if args.seed is not None else random.SystemRandom().getrandbits(64)
boss_room_active = False
boss_battle_complete = False
boss_cage_destroyed = False
boss_cage_destroy_timer = 0.0
boss_cage_blasts = []
player_in_open_space = False
victory_screen_active = False
victory_music_started = pygame.time.get_ticks()
opened_shortcuts = set()
shortcut_blast_timers = {}
boss_wave_stage = 0
boss_triangle_spawn_timer = 0.0
space_rng = random.Random(WORLD_SEED ^ 0x5350414345)
SPACE_STARS = tuple(
    (space_rng.random() * math.tau,
     space_rng.randrange(max(1, int(HEIGHT * 0.54))),
     space_rng.choice(((190, 210, 255), (255, 210, 235), (235, 245, 255))),
     space_rng.choice((1, 1, 1, 2)))
    for _ in range(max(120, WIDTH // 2))
)


def world_hash(cell_x, cell_y):
    """Return a stable pseudo-random value for a world cell this run."""
    value = (WORLD_SEED ^ ((cell_x & WORLD_MASK) * 0x9E3779B185EBCA87)
             ^ ((cell_y & WORLD_MASK) * 0xC2B2AE3D27D4EB4F)) & WORLD_MASK
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & WORLD_MASK
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & WORLD_MASK
    return value ^ (value >> 31)


def world_node_has_hall(node_x, node_y):
    """Select halls at 25% above the original one-in-23 frequency."""
    return world_hash(node_x, node_y) % 92 < 5


def vertical_door_index(edge_x, chunk_y):
    """Choose the shared north/south position for a vertical chunk seam."""
    return world_hash(edge_x * 2, chunk_y * 2 + 1) % MAZE_NODES_PER_SIDE


def horizontal_door_index(chunk_x, edge_y):
    """Choose the shared east/west position for a horizontal chunk seam."""
    return world_hash(chunk_x * 2 + 1, edge_y * 2) % MAZE_NODES_PER_SIDE


def passage_route(chunk_x, chunk_y, first, second):
    """Return a deterministic one-cell-wide route between adjacent maze nodes."""
    node_count = MAZE_NODES_PER_SIDE
    global_x = chunk_x * node_count
    global_y = chunk_y * node_count
    ax, ay = global_x + first[0], global_y + first[1]
    bx, by = global_x + second[0], global_y + second[1]
    vertical = ax == bx
    edge_x = ax if vertical else min(ax, bx)
    edge_y = min(ay, by) if vertical else ay
    route_seed = world_hash(edge_x * 2 + int(vertical), edge_y)
    style = route_seed % 10

    x1, y1 = 3 + first[0] * MAZE_NODE_SPACING, 3 + first[1] * MAZE_NODE_SPACING
    x2, y2 = 3 + second[0] * MAZE_NODE_SPACING, 3 + second[1] * MAZE_NODE_SPACING
    if style < 5:
        if vertical:
            direction = 1 if y2 > y1 else -1
            return [(x1, y1 + direction * step)
                    for step in range(MAZE_NODE_SPACING + 1)]
        direction = 1 if x2 > x1 else -1
        return [(x1 + direction * step, y1)
                for step in range(MAZE_NODE_SPACING + 1)]

    if style == 5:
        # A short 45-degree run, rasterized into cardinally connected cells.
        # This keeps the diagonal appearance while preserving grid movement.
        side = 1 if route_seed & 0x10 else -1
        if vertical:
            direction = 1 if y2 > y1 else -1
            waypoints = [(x1, y1), (x1, y1 + direction),
                         (x1 + side, y1 + direction),
                         (x1 + side, y1 + direction * 2),
                         (x1 + side * 2, y1 + direction * 2),
                         (x1 + side * 2, y1 + direction * 3),
                         (x1 + side * 3, y1 + direction * 3),
                         (x1 + side * 3, y1 + direction * 4),
                         (x1, y1 + direction * 4), (x1, y2)]
        else:
            direction = 1 if x2 > x1 else -1
            waypoints = [(x1, y1), (x1 + direction, y1),
                         (x1 + direction, y1 + side),
                         (x1 + direction * 2, y1 + side),
                         (x1 + direction * 2, y1 + side * 2),
                         (x1 + direction * 3, y1 + side * 2),
                         (x1 + direction * 3, y1 + side * 3),
                         (x1 + direction * 4, y1 + side * 3),
                         (x2, y1 + side * 3), (x2, y1)]
        route = [waypoints[0]]
        for start, end in zip(waypoints, waypoints[1:]):
            dx = 0 if start[0] == end[0] else (1 if end[0] > start[0] else -1)
            dy = 0 if start[1] == end[1] else (1 if end[1] > start[1] else -1)
            x, y = start
            while (x, y) != end:
                x += dx
                y += dy
                route.append((x, y))
        return route

    # The detour stays in the middle of this six-block connection. Its shape
    # comes from the edge hash, so regenerating a chunk never changes it.
    side = 1 if route_seed & 0x10 else -1
    if vertical:
        direction = 1 if y2 > y1 else -1
        waypoints = [(x1, y1), (x1, y1 + direction * 2),
                     (x1 + side, y1 + direction * 2),
                     (x1 + side, y1 + direction * 4),
                     (x1, y1 + direction * 4), (x2, y2)]
    else:
        direction = 1 if x2 > x1 else -1
        waypoints = [(x1, y1), (x1 + direction * 2, y1),
                     (x1 + direction * 2, y1 + side),
                     (x1 + direction * 4, y1 + side),
                     (x1 + direction * 4, y1), (x2, y2)]

    route = [waypoints[0]]
    for start, end in zip(waypoints, waypoints[1:]):
        dx = 0 if start[0] == end[0] else (1 if end[0] > start[0] else -1)
        dy = 0 if start[1] == end[1] else (1 if end[1] > start[1] else -1)
        x, y = start
        while (x, y) != end:
            x += dx
            y += dy
            route.append((x, y))
    return route


@lru_cache(maxsize=512)
def generate_maze_chunk(chunk_x, chunk_y):
    """Build one seeded DFS maze chunk and return its open local blocks."""
    rng = random.Random(world_hash(chunk_x, chunk_y))
    node_count = MAZE_NODES_PER_SIDE
    start = (rng.randrange(node_count), rng.randrange(node_count))
    visited = {start}
    stack = [start]
    passages = []

    # Randomized depth-first search produces a connected, maze-like tree.
    while stack:
        node_x, node_y = stack[-1]
        neighbors = [
            (node_x + dx, node_y + dy)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if 0 <= node_x + dx < node_count
            and 0 <= node_y + dy < node_count
            and (node_x + dx, node_y + dy) not in visited
        ]
        if not neighbors:
            stack.pop()
            continue
        next_node = rng.choice(neighbors)
        passages.append(((node_x, node_y), next_node))
        visited.add(next_node)
        stack.append(next_node)

    open_blocks = set()

    def node_center(node):
        return (3 + node[0] * MAZE_NODE_SPACING,
                3 + node[1] * MAZE_NODE_SPACING)

    chambers = {}
    # Open each maze cell, with an occasional 4x4 chamber around a node.
    for node_x, node_y in visited:
        center_x, center_y = node_center((node_x, node_y))
        global_node_x = chunk_x * node_count + node_x
        global_node_y = chunk_y * node_count + node_y
        has_chamber = world_node_has_hall(global_node_x, global_node_y)
        chambers[(node_x, node_y)] = has_chamber
        if has_chamber:
            for local_y in range(center_y - 1, center_y + 3):
                for local_x in range(center_x - 1, center_x + 3):
                    open_blocks.add((local_x, local_y))
        else:
            open_blocks.add((center_x, center_y))

    # Carve deterministic corridor templates along the DFS connectivity tree.
    # Most links stay straight; the others get short, one-cell-wide zigzags.
    routed_blocks = set()
    for first, second in passages:
        route = passage_route(chunk_x, chunk_y, first, second)
        routed_blocks.update(route)
        open_blocks.update(route)

    # A few internal nodes get a short dead end in an unused direction.
    # Stable node hashes make these optional branches reproducible as well.
    incident = {node: set() for node in visited}
    for first, second in passages:
        dx, dy = second[0] - first[0], second[1] - first[1]
        incident[first].add((dx, dy))
        incident[second].add((-dx, -dy))
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for node_x, node_y in visited:
        if (node_x in (0, node_count - 1) or node_y in (0, node_count - 1)
                or chambers[(node_x, node_y)]):
            continue
        global_node_x = chunk_x * node_count + node_x
        global_node_y = chunk_y * node_count + node_y
        branch_hash = world_hash(global_node_x + 0x1B4D, global_node_y - 0x6C8E)
        if branch_hash % 8 != 0:
            continue
        available = [direction for direction in directions
                     if direction not in incident[(node_x, node_y)]]
        if not available:
            continue
        dx, dy = available[branch_hash % len(available)]
        center_x, center_y = node_center((node_x, node_y))
        length = 1 + ((branch_hash >> 8) & 1)
        branch = [(center_x + dx * step, center_y + dy * step)
                  for step in range(1, length + 1)]
        if not any(cell in routed_blocks for cell in branch):
            open_blocks.update(branch)
            routed_blocks.update(branch)

    # Give some chambers a central obstruction. It is placed off the main
    # north/south and east/west lines, and skipped if a detour uses that cell.
    for (node_x, node_y), has_chamber in chambers.items():
        if not has_chamber:
            continue
        global_node_x = chunk_x * node_count + node_x
        global_node_y = chunk_y * node_count + node_y
        pillar_choice = world_hash(global_node_x + 0x51ED, global_node_y - 0x2A91) % 4
        center_x, center_y = node_center((node_x, node_y))
        pillar = (center_x + (1 if pillar_choice & 1 else -1),
                  center_y + (1 if pillar_choice & 2 else -1))
        if pillar not in routed_blocks:
            open_blocks.discard(pillar)

    # Every side has a seeded doorway. Adjacent chunks derive the same door
    # from their shared edge, so the infinite maze remains connected.
    west_node = (0, vertical_door_index(chunk_x - 1, chunk_y))
    east_node = (node_count - 1, vertical_door_index(chunk_x, chunk_y))
    north_node = (horizontal_door_index(chunk_x, chunk_y - 1), 0)
    south_node = (horizontal_door_index(chunk_x, chunk_y), node_count - 1)

    west_x, west_y = node_center(west_node)
    for local_x in range(0, west_x + 1):
        open_blocks.add((local_x, west_y))
    east_x, east_y = node_center(east_node)
    for local_x in range(east_x, CHUNK_SIZE):
        open_blocks.add((local_x, east_y))
    north_x, north_y = node_center(north_node)
    for local_y in range(0, north_y + 1):
        open_blocks.add((north_x, local_y))
    south_x, south_y = node_center(south_node)
    for local_y in range(south_y, CHUNK_SIZE):
        open_blocks.add((south_x, local_y))

    return frozenset(open_blocks)


def raw_maze_block(cell_x, cell_y):
    """Read the underlying maze block without boss-room modifications."""
    if not (0 < cell_x < WORLD_GRID_BLOCKS - 1
            and 0 < cell_y < WORLD_GRID_BLOCKS - 1):
        return 1
    chunk_x, local_x = divmod(cell_x, CHUNK_SIZE)
    chunk_y, local_y = divmod(cell_y, CHUNK_SIZE)
    return 0 if (local_x, local_y) in generate_maze_chunk(chunk_x, chunk_y) else 1


def find_shortcut_wall_near(target_x, target_y, facing, excluded):
    """Find a seeded wall panel with open floor on both sides of its axis."""
    face_x, face_y = facing
    candidates = []
    radius = 22
    for cell_y in range(max(2, target_y - radius), min(WORLD_GRID_BLOCKS - 2, target_y + radius + 1)):
        for cell_x in range(max(2, target_x - radius), min(WORLD_GRID_BLOCKS - 2, target_x + radius + 1)):
            cell = (cell_x, cell_y)
            if cell in excluded or raw_maze_block(cell_x, cell_y) != 1:
                continue
            if in_boss_room(cell_x, cell_y) or cell in boss_exit_corridors():
                continue
            if (raw_maze_block(cell_x - face_x, cell_y - face_y) != 0
                    or raw_maze_block(cell_x + face_x, cell_y + face_y) != 0):
                continue
            radial_distance = math.hypot(
                cell_x - WORLD_CENTER_BLOCK, cell_y - WORLD_CENTER_BLOCK
            )
            if face_x * (WORLD_CENTER_BLOCK - cell_x) + face_y * (WORLD_CENTER_BLOCK - cell_y) <= 0:
                continue
            candidates.append((
                (cell_x - target_x) ** 2 + (cell_y - target_y) ** 2,
                world_hash(cell_x + 0x5348, cell_y - 0x4F52),
                -radial_distance,
                cell,
            ))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


@lru_cache(maxsize=1)
def hidden_shortcut_pairs():
    """Choose stable outer-to-inner portal pairs from eligible maze walls."""
    chooser = random.Random(WORLD_SEED ^ 0x53484F5254435554)
    pairs = []
    used_cells = set()
    for pair_index in range(16):
        for attempt in range(10):
            angle = math.tau * (pair_index + chooser.uniform(0.12, 0.88)) / 16
            outer_radius = chooser.uniform(185.0, 225.0)
            inner_radius = outer_radius - chooser.uniform(70.0, 105.0)
            face_x, face_y = (int(round(-math.cos(angle))),
                              int(round(-math.sin(angle))))
            if abs(math.cos(angle)) >= abs(math.sin(angle)):
                face_x, face_y = (-1 if math.cos(angle) > 0 else 1), 0
            else:
                face_x, face_y = 0, (-1 if math.sin(angle) > 0 else 1)
            outer_target = (
                round(WORLD_CENTER_BLOCK + math.cos(angle) * outer_radius),
                round(WORLD_CENTER_BLOCK + math.sin(angle) * outer_radius),
            )
            inner_target = (
                round(WORLD_CENTER_BLOCK + math.cos(angle) * inner_radius),
                round(WORLD_CENTER_BLOCK + math.sin(angle) * inner_radius),
            )
            entry = find_shortcut_wall_near(
                *outer_target, (face_x, face_y), used_cells
            )
            if entry is None:
                continue
            exit_wall = find_shortcut_wall_near(
                *inner_target, (face_x, face_y), used_cells | {entry}
            )
            if exit_wall is None:
                continue
            entry_radius = math.hypot(
                entry[0] - WORLD_CENTER_BLOCK, entry[1] - WORLD_CENTER_BLOCK
            )
            exit_radius = math.hypot(
                exit_wall[0] - WORLD_CENTER_BLOCK,
                exit_wall[1] - WORLD_CENTER_BLOCK,
            )
            if entry_radius - exit_radius < 42:
                continue
            pairs.append((entry[0], entry[1], exit_wall[0], exit_wall[1],
                          face_x, face_y))
            used_cells.update((entry, exit_wall))
            break
    return tuple(pairs)


@lru_cache(maxsize=1)
def hidden_shortcut_lookup():
    """Map each entrance wall block to its stable shortcut destination."""
    return {(entry_x, entry_y): pair
            for pair in hidden_shortcut_pairs()
            for entry_x, entry_y in (pair[:2],)}


@lru_cache(maxsize=1)
def boss_exit_corridors():
    """Carve four short corridors that join the central room to the maze."""
    corridors = set()
    for (door_x, door_y), (dx, dy) in zip(BOSS_EXIT_DOORS, BOSS_EXIT_DIRECTIONS):
        cell_x, cell_y = door_x + dx, door_y + dy
        for _ in range(CHUNK_SIZE * 2):
            if not (0 < cell_x < WORLD_GRID_BLOCKS - 1
                    and 0 < cell_y < WORLD_GRID_BLOCKS - 1):
                break
            corridors.add((cell_x, cell_y))
            if raw_maze_block(cell_x, cell_y) == 0:
                break
            cell_x += dx
            cell_y += dy
    return frozenset(corridors)


@lru_cache(maxsize=1)
def boss_escape_corridor_cells():
    """Return the three-block-wide corridor from the winning room exit."""
    cells = set()
    dx, dy = BOSS_ESCAPE_DIRECTION
    side_x, side_y = -dy, dx
    for distance in range(1, BOSS_ESCAPE_CORRIDOR_LENGTH + 1):
        center_x = BOSS_ESCAPE_DOOR[0] + dx * distance
        center_y = BOSS_ESCAPE_DOOR[1] + dy * distance
        for side_offset in (-1, 0, 1):
            cells.add((center_x + side_x * side_offset,
                       center_y + side_y * side_offset))
    return frozenset(cells)


@lru_cache(maxsize=1)
def boss_escape_corridor_wall_cells():
    """Keep corridor walls and the two blocks beside the portal opening."""
    cells = set()
    dx, dy = BOSS_ESCAPE_DIRECTION
    side_x, side_y = -dy, dx
    for distance in range(1, BOSS_ESCAPE_CORRIDOR_LENGTH + 1):
        center_x = BOSS_ESCAPE_DOOR[0] + dx * distance
        center_y = BOSS_ESCAPE_DOOR[1] + dy * distance
        for side_offset in (-2, 2):
            cells.add((center_x + side_x * side_offset,
                       center_y + side_y * side_offset))
    # The corridor is three cells wide, but the portal is one cell wide:
    # retain the two shoulder blocks at the portal plane as the doorway frame.
    portal_x = BOSS_ESCAPE_DOOR[0] + dx * (BOSS_ESCAPE_CORRIDOR_LENGTH + 1)
    portal_y = BOSS_ESCAPE_DOOR[1] + dy * (BOSS_ESCAPE_CORRIDOR_LENGTH + 1)
    for side_offset in (-1, 1):
        cells.add((portal_x + side_x * side_offset,
                   portal_y + side_y * side_offset))
    return frozenset(cells)


@lru_cache(maxsize=1)
def boss_portal_view_cells():
    """Leave a star-filled sightline visible through the far doorway."""
    cells = set()
    dx, dy = BOSS_ESCAPE_DIRECTION
    side_x, side_y = -dy, dx
    for distance in range(1, VIEW_DISTANCE_BLOCKS + 3):
        center_x = BOSS_ESCAPE_PORTAL_CELL[0] + dx * distance
        center_y = BOSS_ESCAPE_PORTAL_CELL[1] + dy * distance
        for side_offset in range(-20, 21):
            cells.add((center_x + side_x * side_offset,
                       center_y + side_y * side_offset))
    return frozenset(cells)


def in_boss_room(cell_x, cell_y):
    return (BOSS_ROOM_LEFT <= cell_x <= BOSS_ROOM_RIGHT
            and BOSS_ROOM_TOP <= cell_y <= BOSS_ROOM_BOTTOM)


def world_cell_type(cell_x, cell_y):
    """Return floor, wall, glass, gate, exit-door, or transparent space-view types."""
    if in_boss_room(cell_x, cell_y):
        if (BOSS_CORE_LEFT <= cell_x <= BOSS_CORE_LEFT + 1
                and BOSS_CORE_TOP <= cell_y <= BOSS_CORE_TOP + 1):
            return 0 if boss_cage_destroyed else 2
        if (cell_x in (BOSS_ROOM_LEFT, BOSS_ROOM_RIGHT)
                or cell_y in (BOSS_ROOM_TOP, BOSS_ROOM_BOTTOM)):
            if (cell_x, cell_y) in BOSS_EXIT_DOORS:
                if not boss_room_active:
                    return 0
                if boss_battle_complete and (cell_x, cell_y) == BOSS_ESCAPE_DOOR:
                    return 0
                return 3
            return 1
        return 0
    if boss_battle_complete:
        if (cell_x, cell_y) in boss_escape_corridor_cells():
            return 0
        if (cell_x, cell_y) in boss_escape_corridor_wall_cells():
            return 1
    if not boss_battle_complete:
        shortcut = hidden_shortcut_lookup().get((cell_x, cell_y))
        if shortcut is not None:
            return 7 if (cell_x, cell_y) in opened_shortcuts else 6
    if boss_battle_complete and (cell_x, cell_y) == BOSS_ESCAPE_PORTAL_CELL:
        return 4
    if player_in_open_space:
        return 0
    if not (0 < cell_x < WORLD_GRID_BLOCKS - 1
            and 0 < cell_y < WORLD_GRID_BLOCKS - 1):
        return 1
    if boss_battle_complete:
        if (cell_x, cell_y) in boss_portal_view_cells():
            return 5
        return 0 if (cell_x, cell_y) in boss_escape_corridor_cells() else 1
    if (cell_x, cell_y) in boss_exit_corridors():
        return 0
    return raw_maze_block(cell_x, cell_y)


def world_block(cell_x, cell_y):
    """Collision lookup; glass cells remain solid while visually transparent."""
    return 0 if world_cell_type(cell_x, cell_y) in (0, 4) else 1


def draw_space_stars(target, wall_tops):
    """Render the world-fixed starfield above wall tops in every area."""
    twinkle = 0.78 + 0.22 * math.sin(pygame.time.get_ticks() * 0.002)
    for star_angle, star_y, color, size in SPACE_STARS:
        relative = (star_angle - player_angle + math.pi) % math.tau - math.pi
        if abs(relative) > HALF_FOV:
            continue
        star_x = min(WIDTH - 1, max(0, int((relative + HALF_FOV) / STEP_ANGLE)))
        sky_limit = min(wall_tops[star_x], HEIGHT // 2)
        if star_y >= sky_limit:
            continue
        tint = tuple(int(channel * twinkle) for channel in color)
        pygame.draw.rect(target, tint, (star_x, star_y, size, size))


def is_maze_dead_end(cell_x, cell_y):
    """A dead end is an open maze block with exactly one open neighbor."""
    if world_block(cell_x, cell_y) != 0:
        return False
    return sum(
        world_block(cell_x + dx, cell_y + dy) == 0
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
    ) == 1


@lru_cache(maxsize=512)
def armor_pickups_in_chunk(chunk_x, chunk_y):
    """Return the seeded armor locations for all dead ends in one chunk."""
    pickups = []
    for local_x, local_y in generate_maze_chunk(chunk_x, chunk_y):
        cell_x = chunk_x * CHUNK_SIZE + local_x
        cell_y = chunk_y * CHUNK_SIZE + local_y
        if in_boss_room(cell_x, cell_y) or (cell_x, cell_y) in boss_exit_corridors():
            continue
        if not is_maze_dead_end(cell_x, cell_y):
            continue
        chance = 0.20 + 0.50 * center_difficulty_factor(
            cell_x * TILE_SIZE, cell_y * TILE_SIZE
        )
        roll = world_hash(cell_x + 0x2A91, cell_y - 0x51ED) / (WORLD_MASK + 1)
        if roll < chance:
            pickups.append((cell_x, cell_y))
    return tuple(pickups)


def generate_map_region(left_cell, top_cell, width, height):
    """Regenerate a rectangular map region, caching each touched chunk once."""
    visible = {}
    for cell_y in range(top_cell, top_cell + height):
        for cell_x in range(left_cell, left_cell + width):
            visible[(cell_x, cell_y)] = world_cell_type(cell_x, cell_y)
    return visible


def generate_visible_map(world_x, world_y, view_distance):
    """Materialize a square nearby view; contents come from the run seed."""
    center_x = math.floor(world_x / TILE_SIZE)
    center_y = math.floor(world_y / TILE_SIZE)
    radius = view_distance + 1
    return generate_map_region(
        center_x - radius, center_y - radius, radius * 2 + 1, radius * 2 + 1
    )


def wall_color_at(world_x, world_y):
    """Sweep once around the hue wheel from green at the edge to the center."""
    block_x = world_x / TILE_SIZE
    block_y = world_y / TILE_SIZE
    edge_distance = max(
        abs(block_x - WORLD_CENTER_BLOCK), abs(block_y - WORLD_CENTER_BLOCK)
    )
    inward_progress = max(
        0.0, min(0.999999, 1.0 - edge_distance / WORLD_CENTER_BLOCK)
    )
    hue = (1.0 / 3.0 + inward_progress) % 1.0
    rgb = colorsys.hsv_to_rgb(hue, 0.95, 1.0)
    return tuple(int(channel * 255) for channel in rgb)


def draw_floor_grid(target, world_x, world_y, wall_depths):
    """Project and wall-clip a dark 4x4 subdivision grid on the floor."""
    floor_grid_layer.fill((0, 0, 0, 0))
    spacing = TILE_SIZE // 4
    max_depth = VIEW_DISTANCE_BLOCKS * TILE_SIZE
    near_depth = 2.0
    view_tangent = math.tan(HALF_FOV)
    camera_cos = math.cos(player_angle)
    camera_sin = math.sin(player_angle)

    def camera_point(point_x, point_y):
        dx, dy = point_x - world_x, point_y - world_y
        return (dx * camera_cos + dy * camera_sin,
                -dx * camera_sin + dy * camera_cos)

    def clip_segment(first, second):
        """Clip a line in camera space to the visible floor frustum."""
        forward0, lateral0 = first
        forward1, lateral1 = second
        df, dl = forward1 - forward0, lateral1 - lateral0
        low, high = 0.0, 1.0
        # Each tuple describes a linear expression that must be >= 0.
        planes = (
            (forward0 - near_depth, df),
            (max_depth - forward0, -df),
            (forward0 * view_tangent - lateral0,
             df * view_tangent - dl),
            (forward0 * view_tangent + lateral0,
             df * view_tangent + dl),
        )
        for value, slope in planes:
            if abs(slope) < 1e-9:
                if value < 0:
                    return None
                continue
            crossing = -value / slope
            if slope > 0:
                low = max(low, crossing)
            else:
                high = min(high, crossing)
            if low > high:
                return None
        return ((forward0 + df * low, lateral0 + dl * low),
                (forward0 + df * high, lateral0 + dl * high))

    def draw_world_line(first_world, second_world):
        clipped = clip_segment(camera_point(*first_world), camera_point(*second_world))
        if clipped is None:
            return
        projected = []
        for forward, lateral in clipped:
            screen_x = (math.atan2(lateral, forward) + HALF_FOV) / STEP_ANGLE
            screen_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / forward
            projected.append((int(screen_x), int(screen_y)))
        midpoint_x = (first_world[0] + second_world[0]) * 0.5
        midpoint_y = (first_world[1] + second_world[1]) * 0.5
        base = wall_color_at(midpoint_x, midpoint_y)
        grid_color = tuple(int(channel * 0.22) for channel in base)
        pygame.draw.line(floor_grid_layer, grid_color, projected[0], projected[1], 1)

    extent = max_depth
    min_x = math.floor((world_x - extent) / spacing) * spacing
    max_x = math.ceil((world_x + extent) / spacing) * spacing
    min_y = math.floor((world_y - extent) / spacing) * spacing
    max_y = math.ceil((world_y + extent) / spacing) * spacing
    for grid_x in range(min_x, max_x + 1, spacing):
        draw_world_line((grid_x, world_y - extent), (grid_x, world_y + extent))
    for grid_y in range(min_y, max_y + 1, spacing):
        draw_world_line((world_x - extent, grid_y), (world_x + extent, grid_y))

    # At each screen column, the wall's projected floor contact marks where
    # the floor becomes visible again. Hide grid pixels above that point.
    for screen_x, wall_depth in enumerate(wall_depths):
        if math.isfinite(wall_depth):
            floor_start = int(HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / wall_depth) + 1
        else:
            floor_start = HEIGHT // 2 + 1
        floor_start = max(0, min(HEIGHT, floor_start))
        if floor_start < HEIGHT:
            target.blit(
                floor_grid_layer, (screen_x, floor_start),
                pygame.Rect(screen_x, floor_start, 1, HEIGHT - floor_start),
            )


def find_spawn_cell():
    """Choose a seeded open cell in the green outer rim of an edge field."""
    edge_fields = [
        (field_x, field_y)
        for field_y in range(WORLD_GRID_BLOCKS // WORLD_FIELD_BLOCKS)
        for field_x in range(WORLD_GRID_BLOCKS // WORLD_FIELD_BLOCKS)
        if field_x in (0, WORLD_GRID_BLOCKS // WORLD_FIELD_BLOCKS - 1)
        or field_y in (0, WORLD_GRID_BLOCKS // WORLD_FIELD_BLOCKS - 1)
    ]
    chooser = random.Random(WORLD_SEED ^ 0x535041574E)
    chooser.shuffle(edge_fields)
    for field_x, field_y in edge_fields:
        left = field_x * WORLD_FIELD_BLOCKS
        top = field_y * WORLD_FIELD_BLOCKS
        cells = []
        for chunk_y in range(top // CHUNK_SIZE, (top + WORLD_FIELD_BLOCKS) // CHUNK_SIZE):
            for chunk_x in range(left // CHUNK_SIZE, (left + WORLD_FIELD_BLOCKS) // CHUNK_SIZE):
                for local_x, local_y in generate_maze_chunk(chunk_x, chunk_y):
                    cell = (chunk_x * CHUNK_SIZE + local_x,
                            chunk_y * CHUNK_SIZE + local_y)
                    if (left <= cell[0] < left + WORLD_FIELD_BLOCKS
                            and top <= cell[1] < top + WORLD_FIELD_BLOCKS
                            and max(abs(cell[0] - WORLD_CENTER_BLOCK),
                                    abs(cell[1] - WORLD_CENTER_BLOCK))
                                >= WORLD_CENTER_BLOCK - 16
                            and world_block(*cell) == 0):
                        cells.append(cell)
        if cells:
            return chooser.choice(cells)
    raise RuntimeError("No open maze cell found in the outer world fields")


def hall_at_cell(cell_x, cell_y):
    """Return the stable hall ID when a world cell lies inside a 4x4 hall."""
    if in_boss_room(cell_x, cell_y) or (cell_x, cell_y) in boss_exit_corridors():
        return None
    chunk_x, local_x = divmod(cell_x, CHUNK_SIZE)
    chunk_y, local_y = divmod(cell_y, CHUNK_SIZE)
    node_x, node_y = local_x // MAZE_NODE_SPACING, local_y // MAZE_NODE_SPACING
    if node_x >= MAZE_NODES_PER_SIDE or node_y >= MAZE_NODES_PER_SIDE:
        return None
    center_x = 3 + node_x * MAZE_NODE_SPACING
    center_y = 3 + node_y * MAZE_NODE_SPACING
    if not (center_x - 1 <= local_x < center_x + 3
            and center_y - 1 <= local_y < center_y + 3):
        return None
    global_node_x = chunk_x * MAZE_NODES_PER_SIDE + node_x
    global_node_y = chunk_y * MAZE_NODES_PER_SIDE + node_y
    if not world_node_has_hall(global_node_x, global_node_y):
        return None
    return global_node_x, global_node_y


def hall_cells(hall_id):
    """Return the open world cells belonging to a generated 4x4 hall."""
    chunk_x, node_x = divmod(hall_id[0], MAZE_NODES_PER_SIDE)
    chunk_y, node_y = divmod(hall_id[1], MAZE_NODES_PER_SIDE)
    center_x = 3 + node_x * MAZE_NODE_SPACING
    center_y = 3 + node_y * MAZE_NODE_SPACING
    return [
        (chunk_x * CHUNK_SIZE + local_x, chunk_y * CHUNK_SIZE + local_y)
        for local_y in range(center_y - 1, center_y + 3)
        for local_x in range(center_x - 1, center_x + 3)
        if world_block(chunk_x * CHUNK_SIZE + local_x,
                       chunk_y * CHUNK_SIZE + local_y) == 0
    ]


def find_maze_path(start, target, max_steps):
    """Find a shortest corridor path, bounded to keep pursuit work predictable."""
    if start == target:
        return [start]
    parents = {start: None}
    distances = {start: 0}
    frontier = deque([start])
    while frontier:
        cell = frontier.popleft()
        distance = distances[cell]
        if distance >= max_steps:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (cell[0] + dx, cell[1] + dy)
            if neighbor in parents or world_block(*neighbor) != 0:
                continue
            parents[neighbor] = cell
            distances[neighbor] = distance + 1
            if neighbor == target:
                path = [target]
                while path[-1] != start:
                    path.append(parents[path[-1]])
                path.reverse()
                return path
            frontier.append(neighbor)
    return None


def triangle_spawn_cell_toward_center(start_cell, min_steps=6, max_steps=20):
    """Choose a spawn point along the shortest walkable route to the maze center."""
    center_approach = (BOSS_CORE_LEFT - 1, BOSS_CORE_TOP)
    path = find_maze_path(
        start_cell, center_approach, WORLD_GRID_BLOCKS * WORLD_GRID_BLOCKS
    )
    if path is None or len(path) < 2:
        return None
    last_step = len(path) - 1
    first_step = min(min_steps, last_step)
    final_step = min(max_steps, last_step)
    return path[random.randint(first_step, final_step)]


FOV = 2 * math.pi / 3  # 120 degrees Field of View
HALF_FOV = FOV / 2
NUM_RAYS = WIDTH  # One ray per column
STEP_ANGLE = FOV / NUM_RAYS
DIST_PLANE = (WIDTH / 2) / math.tan(HALF_FOV)

ENEMY_RADIUS = 18.0
ENEMY_SPAWN_MIN_DISTANCE = TILE_SIZE * 2.0
PLASMA_EXPLOSION_DURATION = 0.28
PLASMA_EXPLOSION_TINT = (130, 255, 160)
SPAWN_FX_DURATION = 0.8
SPAWN_BEAM_LAND_PROGRESS = 0.46
SPAWN_BEAM_LAND_REMAINING = SPAWN_FX_DURATION * (1.0 - SPAWN_BEAM_LAND_PROGRESS)
ENEMY_SPEED = 42.0
TRIANGLE_SPEED = ENEMY_SPEED * 2.0
RECTANGLE_SPEED = ENEMY_SPEED * 0.5
ENEMY_STOP_DISTANCE = 25.0
ENEMY_MAX_TRAVEL_SECONDS = 60.0
ENEMY_MAX_PATH_STEPS = math.ceil(ENEMY_SPEED * ENEMY_MAX_TRAVEL_SECONDS / TILE_SIZE)
ENEMY_ENTRY_DISTANCE_CELLS = 8
ENEMY_REMOTE_DISTANCE = 9 * TILE_SIZE
ENEMY_PATH_REFRESH = 0.3


@lru_cache(maxsize=256)
def make_enemy_texture(base_color, light_bucket, size=24):
    """Build a tiny cel-shaded sphere lit toward the world center."""
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size - 1) / 2
    light_angle = light_bucket * math.tau / 64
    # Texture normals use negative Z for the surface facing the camera.
    light = (-math.cos(light_angle), math.sin(light_angle), 0.38)
    light_length = math.sqrt(sum(component * component for component in light))
    light = tuple(component / light_length for component in light)
    for y in range(size):
        for x in range(size):
            nx = (x - center) / center
            ny = (center - y) / center
            radius_squared = nx * nx + ny * ny
            if radius_squared >= 1.0:
                continue
            nz = math.sqrt(1.0 - radius_squared)
            normal = (-nz, nx, ny)
            diffuse = sum(normal[index] * light[index] for index in range(3))
            if radius_squared > 0.86 or diffuse < 0.12:
                tone = 0.22
            elif diffuse < 0.58:
                tone = 0.58
            else:
                tone = 1.0
            color = tuple(min(255, int(channel * tone)) for channel in base_color)
            texture.set_at((x, y), (*color, 255))
    return texture


@lru_cache(maxsize=64)
def make_triangle_texture(base_color, size=24):
    """Build a small faceted triangle sprite for the faster enemy type."""
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    points = ((size // 2, 1), (size - 2, size - 2), (2, size - 2))
    darker = tuple(int(channel * 0.38) for channel in base_color)
    mid = tuple(int(channel * 0.68) for channel in base_color)
    pygame.draw.polygon(texture, darker, points)
    pygame.draw.polygon(texture, base_color, (points[0], (size // 2, size // 2), points[2]))
    pygame.draw.polygon(texture, mid, (points[0], points[1], (size // 2, size // 2)))
    pygame.draw.polygon(texture, tuple(min(255, c + 45) for c in base_color), points, 1)
    return texture


@lru_cache(maxsize=512)
def make_scaled_triangle_texture(base_color, width, height):
    return pygame.transform.scale(make_triangle_texture(base_color), (width, height))


@lru_cache(maxsize=64)
def make_rectangle_texture(base_color, size=24):
    """Build a beveled, three-tone rectangle enemy sprite."""
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    bounds = pygame.Rect(size // 5, size // 6, size * 3 // 5, size * 2 // 3)
    dark = tuple(int(channel * 0.36) for channel in base_color)
    mid = tuple(int(channel * 0.68) for channel in base_color)
    bright = tuple(min(255, int(channel * 1.18)) for channel in base_color)
    pygame.draw.rect(texture, dark, bounds)
    pygame.draw.polygon(texture, bright, (bounds.topleft, (bounds.centerx, bounds.y + 4),
                                          (bounds.centerx, bounds.bottom - 4),
                                          (bounds.left, bounds.bottom)))
    pygame.draw.polygon(texture, base_color, ((bounds.centerx, bounds.y + 4), bounds.topright,
                                              bounds.bottomright,
                                              (bounds.centerx, bounds.bottom - 4)))
    pygame.draw.rect(texture, bright, bounds, 1)
    return texture


@lru_cache(maxsize=512)
def make_scaled_rectangle_texture(base_color, width, height):
    return pygame.transform.scale(make_rectangle_texture(base_color), (width, height))


def make_armor_texture():
    """Build a small pixel-art vest inspired by the supplied reference."""
    rows = (
        "......####......",
        ".....#SSSS#.....",
        "....#SSSSSS#....",
        "...#SSSSSSSS#...",
        "..#LLSSSSSSLL#..",
        ".#LLL#....#LLL#.",
        "##LL#......#LL##",
        "#LLL#......#LLL#",
        "#LLL#......#LLL#",
        "#LLL#......#LLL#",
        ".#LLLL....LLLL#.",
        ".#LLLLLLLLLLLL#.",
        "..#LLLLLLLLLL#..",
        "..#LLLLLLLLLL#..",
        "...##########...",
        "................",
    )
    palette = {
        "#": (18, 29, 25),
        "L": (190, 215, 200),
        "S": (102, 127, 116),
    }
    texture = pygame.Surface((16, 16), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if pixel in palette:
                texture.set_at((x, y), (*palette[pixel], 255))
    return texture


ARMOR_TEXTURE = make_armor_texture()


def make_health_texture():
    """Build a thick, cell-shaded plus with an outline only on its silhouette."""
    texture = pygame.Surface((16, 16), pygame.SRCALPHA)
    plus_pixels = {
        (x, y)
        for y in range(16)
        for x in range(16)
        if 4 <= x <= 11 or 4 <= y <= 11
    }
    for x, y in plus_pixels:
        outer_edge = any((x + dx, y + dy) not in plus_pixels
                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if outer_edge:
            color = (8, 67, 29)
        elif x <= 6 and y <= 6:
            color = (165, 255, 182)
        elif x >= 9 or y >= 9:
            color = (25, 150, 62)
        else:
            color = (48, 225, 91)
        texture.set_at((x, y), (*color, 255))
    return texture


HEALTH_TEXTURE = make_health_texture()


def make_quad_texture():
    """Build a bright, four-point pixel-art Booster crystal."""
    texture = pygame.Surface((16, 16), pygame.SRCALPHA)
    diamond = ((8, 0), (15, 8), (8, 15), (0, 8))
    pygame.draw.polygon(texture, (72, 20, 112), diamond)
    pygame.draw.polygon(texture, (196, 90, 255), ((8, 2), (13, 8), (8, 13), (2, 8)))
    pygame.draw.polygon(texture, (239, 174, 255), ((8, 2), (8, 8), (2, 8)))
    for point in ((5, 6), (10, 6), (5, 10), (10, 10)):
        pygame.draw.rect(texture, (255, 255, 255), (*point, 2, 2))
    return texture


QUAD_TEXTURE = make_quad_texture()


def make_quad_damage_texture():
    """Build a bright red power core surrounded by chunky rays."""
    texture = pygame.Surface((16, 16), pygame.SRCALPHA)
    pygame.draw.polygon(texture, (160, 20, 24),
                        ((8, 0), (11, 4), (16, 5), (12, 8),
                         (15, 13), (9, 11), (6, 16), (5, 10),
                         (0, 8), (5, 6)))
    pygame.draw.polygon(texture, (255, 42, 35),
                        ((8, 2), (10, 6), (14, 7), (10, 8),
                         (12, 12), (8, 10), (6, 13), (6, 9),
                         (3, 8), (6, 7)))
    pygame.draw.rect(texture, (255, 225, 205), (7, 6, 3, 3))
    return texture


QUAD_DAMAGE_TEXTURE = make_quad_damage_texture()


def make_super_speed_texture():
    """Build a bright, pixelated lightning bolt for the speed pickup."""
    texture = pygame.Surface((16, 16), pygame.SRCALPHA)
    bolt = ((9, 0), (15, 0), (11, 6), (15, 6), (5, 16),
            (7, 9), (3, 9))
    pygame.draw.polygon(texture, (16, 67, 104), bolt)
    pygame.draw.polygon(texture, (70, 210, 255),
                        ((9, 2), (12, 2), (9, 7), (12, 7), (6, 13),
                         (8, 8), (5, 8)))
    pygame.draw.polygon(texture, (205, 250, 255),
                        ((9, 2), (10, 2), (7, 7), (6, 7)))
    return texture


SUPER_SPEED_TEXTURE = make_super_speed_texture()


def enemy_speed(enemy):
    if enemy.get("boss"):
        return 17.0
    if enemy.get("type") == "triangle":
        distance_factor = center_difficulty_factor(enemy["x"], enemy["y"])
        speed = TRIANGLE_SPEED * (1.0 + distance_factor)
        if enemy.get("violet_variant"):
            # A violet wisp gets a modest burst, but remains slower than a
            # sprinting pilot at the game's 60 FPS movement rate.
            speed = min(speed * 1.10, 3.6 * 60.0 * 0.95)
        return speed
    if enemy.get("type") == "rectangle":
        return RECTANGLE_SPEED
    return ENEMY_SPEED


def enemy_hit_multiplier(world_x, world_y):
    return 1.0 + 9.0 * center_difficulty_factor(world_x, world_y)


def center_difficulty_factor(world_x, world_y):
    """Scale difficulty from zero at the border to maximum at world center."""
    block_x = world_x / TILE_SIZE
    block_y = world_y / TILE_SIZE
    edge_distance = max(
        abs(block_x - WORLD_CENTER_BLOCK), abs(block_y - WORLD_CENTER_BLOCK)
    )
    return max(0.0, min(1.0, 1.0 - edge_distance / WORLD_CENTER_BLOCK))


def rectangle_shot_interval(enemy):
    distance_factor = center_difficulty_factor(enemy["x"], enemy["y"])
    rate_multiplier = 1.0 + 1.5 * distance_factor
    return random.uniform(1.0, 5.0) / rate_multiplier


def enemy_hit_points(enemy):
    if enemy.get("boss"):
        return BOSS_MAX_HEALTH
    base_hits = {"sphere": 2, "triangle": 3, "rectangle": 5}.get(
        enemy.get("type"), 2
    )
    return max(1, int(math.ceil(base_hits * enemy.get("hit_multiplier", 1.0))))


def hostile_sphere_color(rng):
    """Choose a vivid hostile-orb hue outside the friendly pink range."""
    hue = rng.random() * 0.80
    return tuple(int(channel * 255) for channel in
                 colorsys.hsv_to_rgb(hue, 0.82, 1.0))


TRIANGLE_YELLOW = (255, 226, 48)
TRIANGLE_VIOLET = (190, 145, 255)
RECTANGLE_RED = (255, 58, 38)
RECTANGLE_BLUE = (65, 150, 255)
QUAD_DAMAGE_COLOR = (190, 70, 255)
QUAD_DAMAGE_ITEM_COLOR = (255, 55, 45)


@lru_cache(maxsize=8)
def make_blue_sentinel_texture(size=24):
    """Build the blue Sentinel body with its cannon mounted on the front."""
    texture = make_rectangle_texture(RECTANGLE_BLUE, size)
    scale = size / 144.0
    pygame.draw.rect(
        texture, (175, 225, 255),
        (int(65 * scale), int(68 * scale), max(1, int(44 * scale)),
         max(1, int(18 * scale))),
    )
    pygame.draw.rect(
        texture, (35, 90, 180),
        (int(94 * scale), int(65 * scale), max(1, int(18 * scale)),
         max(1, int(24 * scale))),
    )
    return texture


@lru_cache(maxsize=512)
def make_scaled_blue_sentinel_texture(width, height):
    return pygame.transform.scale(
        make_blue_sentinel_texture(), (width, height)
    )


def make_enemy_record(cell_x, cell_y, enemy_type, color, hit_multiplier=1.0,
                      blue_cannon=False, violet_variant=False):
    spawn_x = (cell_x + 0.5) * TILE_SIZE
    spawn_y = (cell_y + 0.5) * TILE_SIZE
    if enemy_type == "rectangle":
        color = RECTANGLE_BLUE if blue_cannon else RECTANGLE_RED
    elif enemy_type == "triangle":
        color = TRIANGLE_VIOLET if violet_variant else TRIANGLE_YELLOW
    enemy = {
        "x": spawn_x,
        "y": spawn_y,
        "spawn_x": spawn_x,
        "spawn_y": spawn_y,
        "spawn_fx": SPAWN_FX_DURATION,
        "color": color,
        "type": enemy_type,
        "virtual": False,
        "path_timer": 0.0,
        "next_cell": None,
        "virtual_origin": None,
        "virtual_eta": 0.0,
        "virtual_target_eta": None,
        "virtual_refresh": 0.0,
        "entry_cell": None,
        "hits": 0,
        "hit_multiplier": hit_multiplier,
        "blue_cannon": blue_cannon,
        "violet_variant": violet_variant,
        "animation_phase": world_hash(cell_x + 0x464C, cell_y - 0x4F41)
        / (WORLD_MASK + 1) * math.tau,
    }
    if enemy_type == "rectangle":
        enemy["shot_timer"] = rectangle_shot_interval(enemy)
    return enemy


def spawn_center_triangle(cell_x, cell_y, hit_multiplier):
    """Spawn the regular yellow or violet centerward triangle."""
    global triangle_spawn_flash
    violet_variant = random.random() < 0.20
    enemy = make_enemy_record(
        cell_x, cell_y, "triangle",
        TRIANGLE_VIOLET if violet_variant else TRIANGLE_YELLOW,
        hit_multiplier=hit_multiplier, violet_variant=violet_variant,
    )
    enemies.append(enemy)
    triangle_spawn_flash = 0.24
    play_sfx("violet_triangle_spawn" if violet_variant else "triangle_spawn")
    return enemy


def spawn_center_sentinel(player_cell):
    """Spawn an independent Sentinel 3–6 maze steps toward world center."""
    global rectangle_spawn_flash
    center_approach = (BOSS_CORE_LEFT - 1, BOSS_CORE_TOP)
    path = find_maze_path(
        player_cell, center_approach, WORLD_GRID_BLOCKS * WORLD_GRID_BLOCKS
    )
    if path is None or len(path) <= 3:
        return None
    occupied_cells = {
        (math.floor(enemy["x"] / TILE_SIZE), math.floor(enemy["y"] / TILE_SIZE))
        for enemy in enemies if not enemy.get("friendly")
    }
    spawn_candidates = [
        path[step] for step in range(3, min(6, len(path) - 1) + 1)
        if path[step] not in occupied_cells
    ]
    if not spawn_candidates:
        return None
    cell_x, cell_y = random.choice(spawn_candidates)
    blue_chance = 0.05 + 0.45 * center_difficulty_factor(
        cell_x * TILE_SIZE, cell_y * TILE_SIZE
    )
    blue_cannon = random.random() < blue_chance
    enemy = make_enemy_record(
        cell_x, cell_y, "rectangle",
        RECTANGLE_BLUE if blue_cannon else RECTANGLE_RED,
        hit_multiplier=enemy_hit_multiplier(cell_x * TILE_SIZE, cell_y * TILE_SIZE),
        blue_cannon=blue_cannon,
    )
    enemy["random_center_sentinel"] = True
    enemies.append(enemy)
    rectangle_spawn_flash = 0.34
    play_sfx("rectangle_spawn")
    return enemy


def spawn_debug_enemy(enemy_type, blue_cannon=False):
    """Spawn a requested test enemy three maze blocks from the player."""
    global triangle_spawn_flash, sphere_spawn_flash, rectangle_spawn_flash
    if boss_battle_complete:
        return
    player_cell = (math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE))
    frontier = {player_cell}
    visited = {player_cell}
    candidates = set()
    for step_count in range(1, 7):
        next_frontier = set()
        for cell_x, cell_y in frontier:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = (cell_x + dx, cell_y + dy)
                if neighbor not in visited and world_block(*neighbor) == 0:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            return
        if step_count >= 3:
            candidates = {
                cell for cell in frontier
                if math.hypot((cell[0] + 0.5) * TILE_SIZE - player_x,
                              (cell[1] + 0.5) * TILE_SIZE - player_y)
                >= ENEMY_SPAWN_MIN_DISTANCE
            }
            if candidates:
                break
    if not candidates:
        return

    facing_x, facing_y = math.cos(player_angle), math.sin(player_angle)
    cell_x, cell_y = max(
        candidates,
        key=lambda cell: ((cell[0] - player_cell[0]) * facing_x
                          + (cell[1] - player_cell[1]) * facing_y
                          + random.random() * 0.01),
    )
    if enemy_type == "triangle":
        centerward_cell = triangle_spawn_cell_toward_center(
            player_cell, min_steps=3, max_steps=6
        )
        if centerward_cell is not None:
            cell_x, cell_y = centerward_cell
    violet_variant = enemy_type == "triangle" and random.random() < 0.20
    color = (hostile_sphere_color(random) if enemy_type == "sphere" else
             TRIANGLE_VIOLET if violet_variant else TRIANGLE_YELLOW)
    enemies.append(make_enemy_record(
        cell_x, cell_y, enemy_type, color,
        enemy_hit_multiplier(cell_x * TILE_SIZE, cell_y * TILE_SIZE),
        blue_cannon, violet_variant,
    ))
    if enemy_type == "triangle":
        triangle_spawn_flash = 0.24
        play_sfx("violet_triangle_spawn" if violet_variant else "triangle_spawn")
    elif enemy_type == "rectangle":
        rectangle_spawn_flash = 0.34
        play_sfx("rectangle_spawn")
    else:
        sphere_spawn_flash = 0.28
        play_sfx("sphere_spawn")


def find_debug_pickup_cell():
    """Find a reachable open block a couple of cells ahead of the player."""
    start = (math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE))
    frontier = {start}
    visited = {start}
    candidates = set()
    for distance in range(1, 5):
        next_frontier = set()
        for cell_x, cell_y in frontier:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = (cell_x + dx, cell_y + dy)
                if neighbor not in visited and world_block(*neighbor) == 0:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if distance >= 2 and frontier:
            candidates = frontier
            break
    if not candidates:
        return None
    facing_x, facing_y = math.cos(player_angle), math.sin(player_angle)
    cell_x, cell_y = max(
        candidates,
        key=lambda cell: ((cell[0] - start[0]) * facing_x
                          + (cell[1] - start[1]) * facing_y),
    )
    return cell_x, cell_y


def spawn_debug_armor():
    """Place a test armor pickup a couple of open cells ahead of the player."""
    cell = find_debug_pickup_cell()
    if cell is None:
        return
    cell_x, cell_y = cell
    armor_pickups.append({
        "x": (cell_x + 0.5) * TILE_SIZE,
        "y": (cell_y + 0.5) * TILE_SIZE,
    })


def spawn_debug_health():
    """Place a test health pickup with its maze-block location saved."""
    cell = find_debug_pickup_cell()
    if cell is None:
        return
    cell_x, cell_y = cell
    health_pickups.append({
        "block": (cell_x, cell_y),
        "x": (cell_x + 0.5) * TILE_SIZE,
        "y": (cell_y + 0.5) * TILE_SIZE,
    })


def spawn_debug_quad():
    cell = find_debug_pickup_cell()
    if cell is None:
        return
    cell_x, cell_y = cell
    quad_pickups.append({
        "block": cell,
        "x": (cell_x + 0.5) * TILE_SIZE,
        "y": (cell_y + 0.5) * TILE_SIZE,
    })


def spawn_debug_super_speed():
    cell = find_debug_pickup_cell()
    if cell is None:
        return
    cell_x, cell_y = cell
    super_speed_pickups.append({
        "block": cell,
        "x": (cell_x + 0.5) * TILE_SIZE,
        "y": (cell_y + 0.5) * TILE_SIZE,
    })


def spawn_debug_quad_damage():
    cell = find_debug_pickup_cell()
    if cell is None:
        return
    cell_x, cell_y = cell
    quad_damage_pickups.append({
        "block": cell,
        "x": (cell_x + 0.5) * TILE_SIZE,
        "y": (cell_y + 0.5) * TILE_SIZE,
    })


def spawn_debug_friendly_sphere():
    cell = find_debug_pickup_cell()
    if cell is None:
        return
    cell_x, cell_y = cell
    friend = make_enemy_record(
        cell_x, cell_y, "sphere", (255, 100, 190),
        enemy_hit_multiplier(cell_x * TILE_SIZE, cell_y * TILE_SIZE),
    )
    friend["friendly"] = True
    enemies.append(friend)
    play_sfx("sphere_spawn")


def fire_player_shot(marker_shot=False):
    """Create one player plasma shot or a persistent wall marker."""
    quad_damage_active = not marker_shot and quad_damage_timer > 0.0
    if quad_damage_active:
        play_sfx("quad_damage_fire")
    elif marker_shot:
        play_sfx("fire")
    elif player_weapon_level == 1:
        play_sfx("enemy_shoot")
    elif player_weapon_level >= 2:
        play_sfx("blue_cannon_fire")
    else:
        play_sfx("fire")
    spawn_distance = 14.0
    projectiles.append({
        "x": player_x + math.cos(player_angle) * spawn_distance,
        "y": player_y + math.sin(player_angle) * spawn_distance,
        "angle": player_angle,
        "depth": spawn_distance,
        "explosion": 0.0,
        "age": 0.0,
        "curve_phase": random.random() * math.tau,
        "enemy_kill": False,
        "weapon_tier": player_weapon_level,
        "weapon_color": ((255, 225, 35) if marker_shot else
                         (QUAD_DAMAGE_COLOR if quad_damage_active else
                          PLAYER_WEAPON_COLORS[player_weapon_level])),
        "damage": (0 if marker_shot else
                   (8 if quad_damage_active else
                    PLAYER_WEAPON_DAMAGE[player_weapon_level])),
        "quad_damage": quad_damage_active,
        "marker_projectile": marker_shot,
    })


def quad_blast_hits_player_block(projectile):
    """Return whether a Quad Damage impact shares the player's maze block."""
    if not projectile.get("quad_damage"):
        return False
    projectile_cell = (math.floor(projectile["x"] / TILE_SIZE),
                       math.floor(projectile["y"] / TILE_SIZE))
    player_cell = (math.floor(player_x / TILE_SIZE),
                   math.floor(player_y / TILE_SIZE))
    return projectile_cell == player_cell


def jump_to_nearest_hidden_shortcut():
    """Teleport to the approach side of the nearest unopened shortcut wall."""
    global player_x, player_y, player_angle, player_hall_id
    available = [pair for pair in hidden_shortcut_pairs()
                 if pair[:2] not in opened_shortcuts]
    if not available:
        return
    pair = min(
        available,
        key=lambda item: math.hypot(
            (item[0] + 0.5) * TILE_SIZE - player_x,
            (item[1] + 0.5) * TILE_SIZE - player_y,
        ),
    )
    entry_x, entry_y, _, _, face_x, face_y = pair
    player_x = (entry_x - face_x + 0.5) * TILE_SIZE
    player_y = (entry_y - face_y + 0.5) * TILE_SIZE
    player_angle = math.atan2(face_y, face_x)
    player_hall_id = None


def open_hidden_shortcut(entry_cell):
    """Open a shortcut entrance and start its small blast effect."""
    if entry_cell not in hidden_shortcut_lookup() or entry_cell in opened_shortcuts:
        return False
    opened_shortcuts.add(entry_cell)
    shortcut_blast_timers[entry_cell] = 0.72
    play_sfx("shortcut_break")
    return True


def spawn_hall_enemies(enemies, hall_id):
    """Choose a sphere group or a two-rectangle pack for a newly entered hall."""
    global sphere_spawn_flash, rectangle_spawn_flash
    if boss_battle_complete:
        return
    cells = [
        cell for cell in hall_cells(hall_id)
        if math.hypot((cell[0] + 0.5) * TILE_SIZE - player_x,
                      (cell[1] + 0.5) * TILE_SIZE - player_y)
        >= ENEMY_SPAWN_MIN_DISTANCE
    ]
    if not cells:
        return
    rng = random.Random(world_hash(hall_id[0] + 31337, hall_id[1] - 27183))
    hall_world_x = (hall_id[0] * MAZE_NODE_SPACING + 3) * TILE_SIZE
    hall_world_y = (hall_id[1] * MAZE_NODE_SPACING + 3) * TILE_SIZE
    hit_multiplier = enemy_hit_multiplier(hall_world_x, hall_world_y)
    rectangle_chance = 0.05 + 0.35 * center_difficulty_factor(hall_world_x, hall_world_y)
    if rng.random() < rectangle_chance and len(cells) >= 2:
        blue_cannon_chance = 0.05 + 0.45 * center_difficulty_factor(
            hall_world_x, hall_world_y
        )
        color = tuple(int(channel * 255) for channel in
                      colorsys.hsv_to_rgb(rng.random(), 0.82, 1.0))
        for cell_x, cell_y in rng.sample(cells, 2):
            blue_cannon = rng.random() < blue_cannon_chance
            enemies.append(make_enemy_record(
                cell_x, cell_y, "rectangle", color, hit_multiplier, blue_cannon
            ))
        rectangle_spawn_flash = 0.34
        play_sfx("rectangle_spawn")
        return

    for cell_x, cell_y in rng.sample(cells, min(rng.randint(3, 5), len(cells))):
        color = hostile_sphere_color(rng)
        enemies.append(make_enemy_record(cell_x, cell_y, "sphere", color, hit_multiplier))
    sphere_spawn_flash = 0.28
    play_sfx("sphere_spawn")


def enemy_path(enemy, player_cell):
    if enemy["virtual"]:
        start_cell = enemy["virtual_origin"]
    else:
        start_cell = (math.floor(enemy["x"] / TILE_SIZE), math.floor(enemy["y"] / TILE_SIZE))
    if boss_room_active and in_boss_room(*start_cell) and in_boss_room(*player_cell):
        # The entire arena is visible and compact; don't apply the overworld
        # pursuit limit when routing between opposite sides of the boss room.
        max_steps = BOSS_ROOM_SIZE * BOSS_ROOM_SIZE
    else:
        max_steps = math.ceil(enemy_speed(enemy) * ENEMY_MAX_TRAVEL_SECONDS / TILE_SIZE)
    return find_maze_path(start_cell, player_cell, max_steps)


def set_virtual_approach(enemy, path):
    """Track arrival time and the maze cell where the enemy re-enters view."""
    steps = len(path) - 1
    speed = enemy_speed(enemy)
    travel_seconds = steps * TILE_SIZE / speed
    if travel_seconds > ENEMY_MAX_TRAVEL_SECONDS:
        return False
    entry_steps = max(0, steps - ENEMY_ENTRY_DISTANCE_CELLS)
    target_eta = entry_steps * TILE_SIZE / speed
    if enemy["virtual_target_eta"] is None:
        enemy["virtual_eta"] = target_eta
    else:
        enemy["virtual_eta"] = max(
            0.0, enemy["virtual_eta"] + target_eta - enemy["virtual_target_eta"]
        )
    enemy["virtual_target_eta"] = target_eta
    enemy["entry_cell"] = path[entry_steps]
    enemy["virtual_refresh"] = 0.75
    return True


def update_enemies(enemies, player_x, player_y, delta_time):
    """Move nearby enemies and update distant ones through arrival estimates."""
    player_cell = (math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE))
    survivors = []
    for enemy in enemies:
        if enemy.get("friendly"):
            survivors.append(enemy)
            continue
        if enemy.get("spawn_fx", 0.0) > SPAWN_BEAM_LAND_REMAINING:
            survivors.append(enemy)
            continue
        if enemy["virtual"]:
            enemy["virtual_eta"] = max(0.0, enemy["virtual_eta"] - delta_time)
            enemy["virtual_refresh"] -= delta_time
            if enemy["virtual_refresh"] <= 0.0 or enemy["virtual_eta"] <= 0.0:
                path = enemy_path(enemy, player_cell)
                if path is None or not set_virtual_approach(enemy, path):
                    continue
            if enemy["virtual_eta"] <= 0.0:
                cell_x, cell_y = enemy["entry_cell"]
                enemy["x"] = (cell_x + 0.5) * TILE_SIZE
                enemy["y"] = (cell_y + 0.5) * TILE_SIZE
                enemy["virtual"] = False
                enemy["path_timer"] = 0.0
                enemy["next_cell"] = None
            survivors.append(enemy)
            continue

        player_distance = math.hypot(player_x - enemy["x"], player_y - enemy["y"])
        if player_distance <= ENEMY_STOP_DISTANCE:
            enemy["next_cell"] = None
            enemy["path_timer"] = 0.0
            survivors.append(enemy)
            continue
        enemy_cell = (math.floor(enemy["x"] / TILE_SIZE),
                      math.floor(enemy["y"] / TILE_SIZE))
        enemy_is_in_active_boss_room = (
            boss_room_active and in_boss_room(*enemy_cell)
        )
        if (player_distance > ENEMY_REMOTE_DISTANCE
                and not enemy_is_in_active_boss_room):
            path = enemy_path(enemy, player_cell)
            if path is None:
                continue
            enemy["virtual"] = True
            enemy["virtual_origin"] = (
                math.floor(enemy["x"] / TILE_SIZE), math.floor(enemy["y"] / TILE_SIZE)
            )
            enemy["virtual_target_eta"] = None
            if not set_virtual_approach(enemy, path):
                continue
            survivors.append(enemy)
            continue

        enemy["path_timer"] -= delta_time
        if enemy["path_timer"] <= 0.0:
            path = enemy_path(enemy, player_cell)
            if path is None:
                continue
            enemy["next_cell"] = path[1] if len(path) > 1 else None
            enemy["path_timer"] = ENEMY_PATH_REFRESH

        if enemy["next_cell"] is not None:
            cell_x, cell_y = enemy["next_cell"]
            target_x, target_y = (cell_x + 0.5) * TILE_SIZE, (cell_y + 0.5) * TILE_SIZE
        else:
            target_x, target_y = player_x, player_y
        dx, dy = target_x - enemy["x"], target_y - enemy["y"]
        distance = math.hypot(dx, dy)
        move_distance = min(distance, enemy_speed(enemy) * delta_time)
        if distance > 0.0 and move_distance > 0.0:
            enemy["x"] += dx / distance * move_distance
            enemy["y"] += dy / distance * move_distance
        survivors.append(enemy)
    enemies[:] = survivors


def update_title_demo_enemies(enemies, delta_time):
    """Have title-screen enemies wander randomly around their display hall."""
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for enemy in enemies:
        rng = enemy["wander_rng"]
        target = enemy.get("wander_target")
        if target is None or math.hypot(target[0] - enemy["x"], target[1] - enemy["y"]) < 4:
            cell_x = math.floor(enemy["x"] / TILE_SIZE)
            cell_y = math.floor(enemy["y"] / TILE_SIZE)
            neighbors = [
                (cell_x + dx, cell_y + dy)
                for dx, dy in directions
                if (cell_x + dx, cell_y + dy) in enemy["wander_cells"]
            ]
            if not neighbors:
                enemy["wander_target"] = None
                continue
            target_cell = rng.choice(neighbors)
            target = ((target_cell[0] + 0.5) * TILE_SIZE,
                      (target_cell[1] + 0.5) * TILE_SIZE)
            enemy["wander_target"] = target

        dx, dy = target[0] - enemy["x"], target[1] - enemy["y"]
        distance = math.hypot(dx, dy)
        step = min(distance, enemy["wander_speed"] * delta_time)
        if distance > 0 and step > 0:
            next_x = enemy["x"] + dx / distance * step
            next_y = enemy["y"] + dy / distance * step
            if world_block(math.floor(next_x / TILE_SIZE),
                           math.floor(next_y / TILE_SIZE)) == 0:
                enemy["x"], enemy["y"] = next_x, next_y
            else:
                enemy["wander_target"] = None


def draw_enemy_sphere(target, enemy, wall_depths, player_x, player_y, player_angle):
    """Scale a low-resolution sphere sprite and clip columns behind walls."""
    dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
    distance = math.hypot(dx, dy)
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= ENEMY_RADIUS + 1.0 or distance > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return

    radius = ENEMY_RADIUS
    float_offset = 3.0 * math.sin(
        pygame.time.get_ticks() / 520.0 + enemy.get("animation_phase", 0.0)
    )
    center_z = (radius - TILE_SIZE / 2 + enemy.get("beam_height", 0.0)
                + float_offset)
    bearing = math.atan2(side, forward)
    center_screen_y = HEIGHT / 2 - center_z * DIST_PLANE / forward
    center_screen_x = (bearing + HALF_FOV) / STEP_ANGLE
    sprite_height = max(2, int(2 * radius * DIST_PLANE / forward))
    # The ray view is angular horizontally while the sprites use perspective
    # vertically. Match the projected dimensions so spheres stay circular.
    sprite_width = sprite_height
    sprite_half_angle = sprite_width * STEP_ANGLE / 2
    if bearing + sprite_half_angle <= -HALF_FOV \
            or bearing - sprite_half_angle >= HALF_FOV:
        return
    left = int(center_screen_x - sprite_width / 2)
    top = int(center_screen_y - sprite_height / 2)
    visible_left = max(0, left)
    visible_right = min(WIDTH, left + sprite_width)
    visible_top = max(0, top)
    visible_bottom = min(HEIGHT, top + sprite_height)
    if visible_left >= visible_right or visible_top >= visible_bottom:
        return

    # The apparent light direction is the bearing from this enemy to the
    # world center, rotated into the camera's horizontal coordinate frame.
    origin_angle = math.atan2(
        WORLD_CENTER_WORLD - enemy["y"], WORLD_CENTER_WORLD - enemy["x"]
    )
    relative_light_angle = (origin_angle - player_angle) % math.tau
    light_bucket = int(round(relative_light_angle * 64 / math.tau)) % 64
    # Use chunkier source pixels so the densely shaded sphere reads at the
    # same visual resolution as the more sparsely filled enemy sprites.
    texture = make_enemy_texture(enemy["color"], light_bucket, size=16)
    texture_width, texture_height = texture.get_size()
    crop_left = min(texture_width - 1, max(0, int((visible_left - left) * texture_width / sprite_width)))
    crop_right = min(texture_width, max(
        crop_left + 1, math.ceil((visible_right - left) * texture_width / sprite_width)
    ))
    crop_top = min(texture_height - 1, max(0, int((visible_top - top) * texture_height / sprite_height)))
    crop_bottom = min(texture_height, max(
        crop_top + 1, math.ceil((visible_bottom - top) * texture_height / sprite_height)
    ))
    cropped_texture = texture.subsurface((crop_left, crop_top,
                                          crop_right - crop_left,
                                          crop_bottom - crop_top))
    visible_width = visible_right - visible_left
    visible_height = visible_bottom - visible_top
    sprite = pygame.transform.scale(cropped_texture, (visible_width, visible_height))
    source_rect_y = pygame.Rect(0, 0, 1, visible_height)
    for screen_x in range(visible_left, visible_right):
        if forward >= wall_depths[screen_x]:
            continue
        source_rect_y.x = screen_x - visible_left
        target.blit(sprite, (screen_x, visible_top), source_rect_y)


def draw_sphere_tractor_beam(target, sphere, wall_depths, player_x, player_y,
                             player_angle):
    """Draw a soft vertical beam lifting a rescued sphere through the exit."""
    dx, dy = sphere["x"] - player_x, sphere["y"] - player_y
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= 1.0 or forward > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return
    bearing = math.atan2(side, forward)
    if abs(bearing) > HALF_FOV:
        return
    screen_x = int((bearing + HALF_FOV) / STEP_ANGLE)
    if not 0 <= screen_x < len(wall_depths) or forward >= wall_depths[screen_x]:
        return
    floor_y = int(HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / forward)
    beam_top = int(HEIGHT / 2 - (TILE_SIZE / 2 + sphere["beam_height"])
                   * DIST_PLANE / forward)
    beam_width = max(2, int(11 * DIST_PLANE / forward))
    pulse = 0.72 + 0.28 * math.sin(pygame.time.get_ticks() * 0.025)
    alpha = int(135 * pulse)
    left = screen_x - beam_width // 2
    pygame.draw.rect(
        target, (255, 105, 210, alpha),
        (left, max(0, beam_top), beam_width, max(1, floor_y - max(0, beam_top))),
    )
    pygame.draw.line(
        target, (255, 240, 255, min(255, alpha + 75)),
        (screen_x, max(0, beam_top)), (screen_x, floor_y), max(1, beam_width // 4),
    )


def draw_enemy_triangle(target, enemy, wall_depths, player_x, player_y, player_angle):
    """Project and wall-clip the faceted triangle enemy."""
    dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
    distance = math.hypot(dx, dy)
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= ENEMY_RADIUS + 1.0 or distance > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return
    bearing = math.atan2(side, forward)
    center_x = (bearing + HALF_FOV) / STEP_ANGLE
    # These sprites face the camera, so pinhole scale is their forward depth.
    apparent_radius = ENEMY_RADIUS * DIST_PLANE / forward
    width = max(2, min(WIDTH * 2, int(apparent_radius * 2.2)))
    height = max(2, min(HEIGHT * 2, int(apparent_radius * 2.4)))
    sway_phase = enemy.get("animation_phase", 0.0)
    sway = math.sin(pygame.time.get_ticks() / 520.0 + sway_phase) * max(1.0, width * 0.045)
    center_x += sway
    center_z = ENEMY_RADIUS - TILE_SIZE / 2
    center_y = HEIGHT / 2 - center_z * DIST_PLANE / forward
    left, top = int(center_x - width / 2), int(center_y - height / 2)
    visible_left, visible_right = max(0, left), min(WIDTH, left + width)
    visible_top, visible_bottom = max(0, top), min(HEIGHT, top + height)
    if visible_left >= visible_right or visible_top >= visible_bottom:
        return
    sprite = make_scaled_triangle_texture(enemy["color"], width, height)
    for x in range(visible_left, visible_right):
        # The wall buffer stores cosine-corrected forward depth. These enemy
        # sprites are camera-facing billboards on a constant-forward plane.
        if forward >= wall_depths[x]:
            continue
        source_x = x - left
        target.blit(sprite, (x, visible_top), pygame.Rect(source_x, visible_top - top, 1,
                                                          visible_bottom - visible_top))


def draw_enemy_rectangle(target, enemy, wall_depths, player_x, player_y, player_angle):
    """Project and wall-clip a beveled rectangular enemy."""
    dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
    distance = math.hypot(dx, dy)
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= ENEMY_RADIUS + 1.0 or distance > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return
    bearing = math.atan2(side, forward)
    center_x = (bearing + HALF_FOV) / STEP_ANGLE
    # These sprites face the camera, so pinhole scale is their forward depth.
    boss_scale = 3.0 if enemy.get("boss") else 1.0
    apparent_radius = ENEMY_RADIUS * boss_scale * DIST_PLANE / forward
    width = max(2, min(WIDTH * 2, int(apparent_radius * 2.5)))
    height = max(2, min(HEIGHT * 2, int(apparent_radius * 2.75)))
    sway_phase = enemy.get("animation_phase", 0.0)
    sway = math.sin(pygame.time.get_ticks() / 520.0 + sway_phase) * max(1.0, width * 0.035)
    center_x += sway
    center_z = ENEMY_RADIUS - TILE_SIZE / 2
    center_y = HEIGHT / 2 - center_z * DIST_PLANE / forward
    left, top = int(center_x - width / 2), int(center_y - height / 2)
    visible_left, visible_right = max(0, left), min(WIDTH, left + width)
    visible_top, visible_bottom = max(0, top), min(HEIGHT, top + height)
    if visible_left >= visible_right or visible_top >= visible_bottom:
        return
    if enemy.get("blue_cannon"):
        sprite = make_scaled_blue_sentinel_texture(width, height)
    else:
        sprite = make_scaled_rectangle_texture(enemy["color"], width, height)
    for x in range(visible_left, visible_right):
        if forward >= wall_depths[x]:
            continue
        target.blit(sprite, (x, visible_top), pygame.Rect(
            x - left, visible_top - top, 1, visible_bottom - visible_top
        ))


def draw_flat_pickup(target, pickup, texture, wall_depths,
                     player_x, player_y, player_angle):
    """Project a flat pixel-art item into the view and clip it by walls."""
    dx, dy = pickup["x"] - player_x, pickup["y"] - player_y
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= 1.0 or forward > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return
    bearing = math.atan2(side, forward)
    if abs(bearing) > HALF_FOV:
        return
    center_x = (bearing + HALF_FOV) / STEP_ANGLE
    floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / forward
    sprite_height = max(8, int(30 * DIST_PLANE / forward))
    sprite_width = max(8, int(30 * DIST_PLANE / forward))
    sprite = pygame.transform.scale(texture, (sprite_width, sprite_height))
    left = int(center_x - sprite_width / 2)
    top = int(floor_y - sprite_height)
    for screen_x in range(max(0, left), min(WIDTH, left + sprite_width)):
        ray_depth = forward / max(0.001, math.cos(
            (-HALF_FOV + screen_x * STEP_ANGLE) - bearing
        ))
        if ray_depth >= wall_depths[screen_x]:
            continue
        target.blit(sprite, (screen_x, top), pygame.Rect(
            screen_x - left, 0, 1, sprite_height
        ))


def draw_armor_pickup(target, pickup, wall_depths, player_x, player_y, player_angle):
    draw_flat_pickup(target, pickup, ARMOR_TEXTURE, wall_depths,
                     player_x, player_y, player_angle)


def draw_health_pickup(target, pickup, wall_depths, player_x, player_y, player_angle):
    draw_flat_pickup(target, pickup, HEALTH_TEXTURE, wall_depths,
                     player_x, player_y, player_angle)


def draw_quad_pickup(target, pickup, wall_depths, player_x, player_y, player_angle):
    draw_flat_pickup(target, pickup, QUAD_TEXTURE, wall_depths,
                     player_x, player_y, player_angle)


def draw_quad_damage_pickup(target, pickup, wall_depths,
                            player_x, player_y, player_angle):
    draw_flat_pickup(target, pickup, QUAD_DAMAGE_TEXTURE, wall_depths,
                     player_x, player_y, player_angle)


def draw_super_speed_pickup(target, pickup, wall_depths,
                            player_x, player_y, player_angle):
    draw_flat_pickup(target, pickup, SUPER_SPEED_TEXTURE, wall_depths,
                     player_x, player_y, player_angle)


def draw_player_marker(target, marker, wall_depths, player_x, player_y, player_angle):
    """Render a persistent, gently pulsing marker orb stuck to a wall."""
    dx, dy = marker["x"] - player_x, marker["y"] - player_y
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= 1.0 or forward > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return
    bearing = math.atan2(side, forward)
    if abs(bearing) > HALF_FOV:
        return
    center_x = (bearing + HALF_FOV) / STEP_ANGLE
    pulse = 0.86 + 0.14 * math.sin(pygame.time.get_ticks() * 0.006 + marker["phase"])
    radius = max(6, int(18.0 * DIST_PLANE / forward * pulse))
    diameter = radius * 2
    texture = pygame.transform.scale(
        make_colored_plasma_texture((255, 225, 35)), (diameter, diameter)
    )
    left = int(center_x - radius)
    top = int(HEIGHT / 2 - radius)
    for screen_x in range(max(0, left), min(WIDTH, left + diameter)):
        # wall_depths stores cosine-corrected forward depth, so compare it to
        # this marker's forward distance rather than its raw ray distance.
        if forward >= wall_depths[screen_x]:
            continue
        source_column = pygame.Rect(screen_x - left, 0, 1, diameter)
        target.blit(texture, (screen_x, top), source_column)
        target.blit(texture, (screen_x, top), source_column,
                    special_flags=pygame.BLEND_RGBA_ADD)


@lru_cache(maxsize=64)
def make_spawn_beam_texture(color):
    """Create a narrow, feathered beam with a bright core for enemy arrivals."""
    width, height = 48, 128
    beam = pygame.Surface((width, height), pygame.SRCALPHA)
    for y in range(height):
        vertical = min(1.0, (y + 1) / 18.0, (height - y) / 18.0)
        for x in range(width):
            normalized_x = (x - (width - 1) / 2) / ((width - 1) / 2)
            spread = math.exp(-normalized_x * normalized_x * 10.0)
            alpha = int(230 * spread * vertical)
            core = max(0.0, 1.0 - abs(normalized_x) * 3.5)
            rgb = tuple(int(channel * (1.0 - core) + 255 * core) for channel in color)
            beam.set_at((x, y), (*rgb, alpha))
    return beam


@lru_cache(maxsize=1)
def make_spawn_portal_ring():
    ring = pygame.Surface((80, 24), pygame.SRCALPHA)
    pygame.draw.ellipse(ring, (175, 90, 255, 55), (2, 3, 76, 18))
    pygame.draw.ellipse(ring, (225, 200, 255, 225), (3, 4, 74, 16), 2)
    pygame.draw.ellipse(ring, (255, 255, 255, 170), (15, 7, 50, 10), 1)
    return ring


def draw_enemy_spawn_portal(target, enemy, wall_depths, player_x, player_y, player_angle):
    remaining = enemy.get("spawn_fx", 0.0)
    if remaining <= 0.0:
        return
    dx, dy = enemy["spawn_x"] - player_x, enemy["spawn_y"] - player_y
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if (forward <= 1.0 or math.hypot(dx, dy) > VIEW_DISTANCE_BLOCKS * TILE_SIZE):
        return
    bearing = math.atan2(side, forward)
    if abs(bearing) > HALF_FOV:
        return
    center_x = int((bearing + HALF_FOV) / STEP_ANGLE)
    ground_y = int(HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / forward)
    progress = min(1.0, max(0.0, 1.0 - remaining / SPAWN_FX_DURATION))
    beam_front = int(min(HEIGHT, ground_y) * min(1.0, progress / SPAWN_BEAM_LAND_PROGRESS))
    beam_height = max(2, beam_front)
    beam_width = max(4, min(WIDTH * 2, int(TILE_SIZE * 0.68 * DIST_PLANE / forward)))
    beam = pygame.transform.smoothscale(
        make_spawn_beam_texture(enemy["color"]), (beam_width, beam_height)
    )
    beam.set_alpha(int(255 * min(1.0, remaining / SPAWN_FX_DURATION)))
    beam_left, beam_top = center_x - beam_width // 2, 0
    for x in range(max(0, beam_left), min(WIDTH, beam_left + beam_width)):
        if forward >= wall_depths[x]:
            continue
        target.blit(beam, (x, beam_top), pygame.Rect(
            x - beam_left, 0, 1, beam_height
        ))

    if progress < SPAWN_BEAM_LAND_PROGRESS and beam_front > 1:
        flare_y = min(HEIGHT - 1, beam_front)
        flare_color = tuple(min(255, int(channel * 0.72 + 255 * 0.28))
                            for channel in enemy["color"])
        flare_half_height = max(1, beam_width // 8)
        for x in range(max(0, beam_left), min(WIDTH, beam_left + beam_width)):
            if forward < wall_depths[x]:
                pygame.draw.line(target, flare_color, (x, flare_y - flare_half_height),
                                 (x, flare_y + flare_half_height), 1)

    ring_width = max(5, min(WIDTH * 2, int(TILE_SIZE * 0.9 * DIST_PLANE / forward)))
    ring_height = max(3, min(HEIGHT * 2, int(TILE_SIZE * 0.18 * DIST_PLANE / forward)))
    ring = pygame.transform.smoothscale(make_spawn_portal_ring(), (ring_width, ring_height))
    ring_alpha = int(255 * min(1.0, remaining / SPAWN_FX_DURATION)
                     * min(1.0, max(0.0, (progress - 0.32) / 0.18)))
    ring.set_alpha(ring_alpha)
    ring_left, ring_top = center_x - ring_width // 2, ground_y - ring_height // 2
    for x in range(max(0, ring_left), min(WIDTH, ring_left + ring_width)):
        if forward >= wall_depths[x]:
            continue
        target.blit(ring, (x, ring_top), pygame.Rect(x - ring_left, 0, 1, ring_height))


@lru_cache(maxsize=8)
def make_colored_plasma_texture(tint, size=48):
    """Build a soft, layered plasma orb in the requested color."""
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size - 1) / 2
    outer = tuple(int(channel * 0.68) for channel in tint)
    middle = tuple(min(255, int(channel * 1.06)) for channel in tint)
    core = tuple(min(255, int(channel * 0.42 + 255 * 0.58)) for channel in tint)
    for y in range(size):
        for x in range(size):
            radius = math.hypot(x - center, y - center) / center
            if radius >= 1.0:
                continue
            if radius >= 0.68:
                color, alpha = outer, 80
            elif radius >= 0.34:
                color, alpha = middle, 150
            else:
                color, alpha = core, 235
            edge_fade = min(1.0, (1.0 - radius) * 12.0)
            texture.set_at((x, y), (*color, int(alpha * edge_fade)))
    return texture


@lru_cache(maxsize=512)
def make_scaled_plasma_texture(tint, diameter):
    return pygame.transform.smoothscale(
        make_colored_plasma_texture(tint), (diameter, diameter)
    )


@lru_cache(maxsize=64)
def make_enemy_explosion_texture(enemy_color, size=96):
    """Make a noisy radial blast whose glow inherits the defeated enemy's hue."""
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    rng = random.Random(sum((index + 1) * channel
                            for index, channel in enumerate(enemy_color)))
    center = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            nx = (x - center) / center
            ny = (y - center) / center
            radius = math.sqrt(nx * nx + ny * ny)
            edge = radius + rng.uniform(-0.045, 0.045)
            if edge >= 1.0:
                continue
            falloff = max(0.0, 1.0 - edge) ** 0.55
            core = max(0.0, 1.0 - radius * 2.2)
            noise = rng.uniform(0.68, 1.12)
            color = tuple(min(255, int(channel * (0.58 + core * 0.68) * noise
                                  + 255 * core * 0.30))
                          for channel in enemy_color)
            alpha = min(255, int(255 * falloff * noise))
            texture.set_at((x, y), (*color, alpha))
    return texture


def draw_hostile_projectile(target, shot, wall_depths, player_x, player_y, player_angle):
    dx, dy = shot["x"] - player_x, shot["y"] - player_y
    distance = math.hypot(dx, dy)
    relative = (math.atan2(dy, dx) - player_angle + math.pi) % math.tau - math.pi
    depth = distance * math.cos(relative)
    if depth <= 1.0 or depth > VIEW_DISTANCE_BLOCKS * TILE_SIZE or abs(relative) > HALF_FOV:
        return
    screen_x = int((relative + HALF_FOV) / STEP_ANGLE)
    if shot.get("explosion", 0.0) > 0.0:
        progress = 1.0 - shot["explosion"] / PLASMA_EXPLOSION_DURATION
        radius_world = 4.0 + progress * 38.0
    else:
        radius_world = 5.5
    scale = 2.0 if shot.get("blue_cannon") else 1.0
    radius = max(2, int(radius_world * scale * DIST_PLANE / depth))
    diameter = radius * 2
    tint = shot.get("plasma_color", (70, 155, 255)
                    if shot.get("blue_cannon") else (255, 58, 38))
    sprite = make_scaled_plasma_texture(tint, diameter)
    left, top = screen_x - radius, int(HEIGHT / 2) - radius
    for x in range(max(0, left), min(WIDTH, left + diameter)):
        if depth >= wall_depths[x]:
            continue
        target.blit(sprite, (x, top), pygame.Rect(x - left, 0, 1, diameter))


# Player Parameters
spawn_cell_x, spawn_cell_y = find_spawn_cell()
player_x = (spawn_cell_x + 0.5) * TILE_SIZE
player_y = (spawn_cell_y + 0.5) * TILE_SIZE
player_angle = 0.0
projectiles = []
player_markers = []
hostile_projectiles = []
enemies = []
boss_spheres = []
armor_pickups = []
health_pickups = []
quad_pickups = []
quad_damage_pickups = []
super_speed_pickups = []
loaded_armor_chunks = set()
MAX_PLAYER_MARKERS = 20
SUPER_SPEED_FIRE_INTERVAL = 0.10
MAX_ARMOR_HITS = 10
ARMOR_HITS_PER_PICKUP = 5
armor_hits_remaining = 0
super_speed_timer = 0.0
quad_damage_timer = 0.0
player_fire_timer = 0.0
player_hall_id = None

def print_map_png(filename=None):
    """Build the complete seeded map, optionally saving it as a PNG."""
    pixels_per_block = 8 if args.super_resolution else 2
    blocks_wide = blocks_high = WORLD_GRID_BLOCKS
    image_width = blocks_wide * pixels_per_block
    image_height = blocks_high * pixels_per_block
    left_cell = top_cell = 0
    visible = generate_map_region(left_cell, top_cell, blocks_wide, blocks_high)

    map_image = pygame.Surface((image_width, image_height))
    map_image.fill((10, 12, 18))
    for row in range(blocks_high):
        cell_y = top_cell + row
        for column in range(blocks_wide):
            cell_x = left_cell + column
            rect = pygame.Rect(column * pixels_per_block, row * pixels_per_block,
                               pixels_per_block, pixels_per_block)
            cell_type = visible.get((cell_x, cell_y), 1)
            if cell_type == 2:
                color = (112, 42, 82)
            elif cell_type == 3:
                color = BOSS_EXIT_COLOR
            elif cell_type == 6:
                color = (245, 55, 205)
            elif cell_type == 7:
                color = (110, 220, 245)
            elif cell_type:
                color = wall_color_at((cell_x + 0.5) * TILE_SIZE,
                                      (cell_y + 0.5) * TILE_SIZE)
            else:
                color = (18, 21, 27)
            map_image.fill(color, rect)
            if pixels_per_block > 2:
                pygame.draw.rect(map_image, (25, 28, 35), rect, 1)

    def cell_point(cell_x, cell_y):
        return ((cell_x - left_cell) * pixels_per_block + pixels_per_block // 2,
                (cell_y - top_cell) * pixels_per_block + pixels_per_block // 2)

    # Draw each secret route as a straight connector, with distinct entrance
    # and destination markers so the paired wall panels are easy to identify.
    shortcut_line_width = max(1, pixels_per_block // 2)
    shortcut_marker_radius = max(2, pixels_per_block)
    for entry_x, entry_y, exit_x, exit_y, _, _ in hidden_shortcut_pairs():
        entry_point = cell_point(entry_x, entry_y)
        exit_point = cell_point(exit_x, exit_y)
        pygame.draw.line(
            map_image, (12, 10, 24), entry_point, exit_point,
            shortcut_line_width + 2,
        )
        pygame.draw.line(
            map_image, (255, 95, 225), entry_point, exit_point,
            shortcut_line_width,
        )
        pygame.draw.circle(map_image, (255, 65, 210), entry_point,
                           shortcut_marker_radius)
        pygame.draw.circle(map_image, (70, 235, 255), exit_point,
                           shortcut_marker_radius)

    # Mark the seeded player start and all deterministic armor spawn cells.
    player_point = cell_point(spawn_cell_x, spawn_cell_y)
    marker_radius = max(3, pixels_per_block * 2)
    pygame.draw.circle(map_image, (245, 250, 255), player_point, marker_radius)
    pygame.draw.line(
        map_image, (245, 250, 255), player_point,
        (player_point[0] + pixels_per_block * 7, player_point[1]),
        max(2, pixels_per_block),
    )
    armor_sprite = (
        (0, 1, 1, 1, 0),
        (1, 1, 2, 1, 1),
        (1, 2, 2, 2, 1),
        (0, 1, 2, 1, 0),
        (0, 0, 1, 0, 0),
    )
    armor_colors = {1: (8, 92, 35), 2: (55, 255, 105)}
    armor_pixel_size = max(1, pixels_per_block // 2)

    def draw_armor_marker(cell_x, cell_y):
        center_x, center_y = cell_point(cell_x, cell_y)
        sprite_left = center_x - len(armor_sprite[0]) * armor_pixel_size // 2
        sprite_top = center_y - len(armor_sprite) * armor_pixel_size // 2
        for row_index, row in enumerate(armor_sprite):
            for column_index, shade in enumerate(row):
                if shade:
                    pygame.draw.rect(
                        map_image, armor_colors[shade],
                        (sprite_left + column_index * armor_pixel_size,
                         sprite_top + row_index * armor_pixel_size,
                         armor_pixel_size, armor_pixel_size),
                    )

    for chunk_y in range(WORLD_CHUNKS_PER_SIDE):
        for chunk_x in range(WORLD_CHUNKS_PER_SIDE):
            for cell_x, cell_y in armor_pickups_in_chunk(chunk_x, chunk_y):
                draw_armor_marker(cell_x, cell_y)
    for pickup in health_pickups:
        health_cell_x, health_cell_y = pickup["block"]
        item_point = cell_point(health_cell_x, health_cell_y)
        pygame.draw.circle(
            map_image, (5, 60, 20), item_point, marker_radius + pixels_per_block
        )
        pygame.draw.circle(map_image, (80, 255, 110), item_point, marker_radius)
    for pickup in quad_pickups:
        item_point = cell_point(*pickup["block"])
        pygame.draw.circle(
            map_image, (72, 20, 112), item_point, marker_radius + pixels_per_block
        )
        pygame.draw.circle(map_image, (210, 130, 255), item_point, marker_radius)
    for pickup in super_speed_pickups:
        item_point = cell_point(*pickup["block"])
        pygame.draw.circle(map_image, (12, 50, 92), item_point,
                           marker_radius + pixels_per_block)
        pygame.draw.circle(map_image, (85, 220, 255), item_point, marker_radius)
    for pickup in quad_damage_pickups:
        item_point = cell_point(*pickup["block"])
        pygame.draw.circle(map_image, (78, 8, 14), item_point,
                           marker_radius + pixels_per_block)
        pygame.draw.circle(map_image, QUAD_DAMAGE_ITEM_COLOR, item_point, marker_radius)

    if filename is None:
        return map_image
    output_path = Path(filename).expanduser().resolve()
    pygame.image.save(map_image, str(output_path))
    print(f"Saved map to {output_path} (seed {WORLD_SEED})")

def print_sprite_sheet_png(filename):
    """Export the game's reusable sprite textures and color variants."""
    keycaps = pygame.Surface((144, 144), pygame.SRCALPHA)
    key_font = pygame.font.SysFont("monospace", 10, bold=True)
    for label, rect in (
        ("W", (60, 12, 24, 22)), ("A", (32, 38, 24, 22)),
        ("S", (60, 38, 24, 22)), ("D", (88, 38, 24, 22)),
        ("J", (30, 72, 24, 22)), ("K", (60, 72, 24, 22)),
        ("F", (90, 72, 24, 22)), ("ESC", (12, 110, 38, 22)),
        ("SPACE", (58, 110, 74, 22)),
    ):
        pygame.draw.rect(keycaps, (8, 24, 18), rect, border_radius=4)
        pygame.draw.rect(keycaps, (70, 255, 130), rect, 2, border_radius=4)
        glyph = key_font.render(label, True, (225, 255, 232))
        keycaps.blit(glyph, (rect[0] + (rect[2] - glyph.get_width()) // 2,
                             rect[1] + (rect[3] - glyph.get_height()) // 2))

    sprites = [
        ("Hostile sphere", make_enemy_texture((80, 240, 135), 12, size=24), 92),
        ("Friendly pink sphere", make_enemy_texture((255, 100, 190), 12, size=24), 92),
        ("Yellow triangle", make_triangle_texture(TRIANGLE_YELLOW), 92),
        ("Violet triangle", make_triangle_texture(TRIANGLE_VIOLET), 92),
        ("Red Sentinel", make_rectangle_texture(RECTANGLE_RED), 92),
        ("Blue Sentinel", make_blue_sentinel_texture(), 92),
        ("Rectangulus", make_rectangle_texture(RECTANGLE_RED), 124),
        ("Aegis armor", ARMOR_TEXTURE, 92),
        ("Vital Spark health", HEALTH_TEXTURE, 92),
        ("Booster", QUAD_TEXTURE, 92),
        ("Quad Damage", QUAD_DAMAGE_TEXTURE, 92),
        ("Super Speed", SUPER_SPEED_TEXTURE, 92),
        ("Player plasma B", make_colored_plasma_texture(PLASMA_EXPLOSION_TINT), 62),
        ("Player plasma A", make_colored_plasma_texture((255, 58, 38)), 62),
        ("Player plasma S", make_colored_plasma_texture((70, 155, 255)), 62),
        ("Yellow wall marker", make_colored_plasma_texture((255, 225, 35)), 62),
        ("Enemy red plasma", make_colored_plasma_texture((255, 58, 38)), 62),
        ("Heavy blue plasma", make_colored_plasma_texture((70, 155, 255)), 92),
        ("Enemy death burst", make_enemy_explosion_texture((255, 226, 48)), 96),
        ("Red spawn beam", make_spawn_beam_texture(RECTANGLE_RED), 82),
        ("Violet spawn beam", make_spawn_beam_texture(TRIANGLE_VIOLET), 82),
        ("Spawn portal ring", make_spawn_portal_ring(), 128),
        ("Control keycaps", keycaps, 132),
        ("Violet floor glow", make_floor_reflection_gradient(14, (195, 105, 255)), 132),
        ("Green enemy floor glow", make_enemy_floor_gradient((80, 240, 135)), 132),
    ]

    columns = 4
    cell_width, cell_height = 270, 190
    rows = math.ceil(len(sprites) / columns)
    header_height = 72
    sheet = pygame.Surface((columns * cell_width, header_height + rows * cell_height))
    sheet.fill((7, 10, 18))
    title_font = pygame.font.SysFont("monospace", 28, bold=True)
    subtitle_font = pygame.font.SysFont("monospace", 13, bold=True)
    label_font = pygame.font.SysFont("monospace", 15, bold=True)
    sheet.blit(title_font.render("SHAP3D SPRITE ATLAS", True, (240, 248, 255)), (22, 12))
    sheet.blit(subtitle_font.render(
        f"{len(sprites)} SPRITES // ENEMIES, ITEMS, PLASMA, FX, UI", True,
        (90, 255, 145)), (24, 47))

    for index, (label, sprite, display_size) in enumerate(sprites):
        column, row = index % columns, index // columns
        cell_x = column * cell_width
        cell_y = header_height + row * cell_height
        cell_rect = pygame.Rect(cell_x + 5, cell_y + 5, cell_width - 10, cell_height - 10)
        pygame.draw.rect(sheet, (18, 22, 31), cell_rect)
        pygame.draw.rect(sheet, (49, 59, 75), cell_rect, 1)
        image_area = pygame.Rect(cell_x + 18, cell_y + 16, cell_width - 36, 130)
        checker_size = 10
        for checker_y in range(image_area.top, image_area.bottom, checker_size):
            for checker_x in range(image_area.left, image_area.right, checker_size):
                shade = (27, 32, 42) if ((checker_x // checker_size)
                                          + (checker_y // checker_size)) % 2 else (20, 25, 34)
                pygame.draw.rect(sheet, shade, (checker_x, checker_y,
                                                checker_size, checker_size))
        sprite_width, sprite_height = sprite.get_size()
        scale = min(display_size / max(sprite_width, sprite_height),
                    (image_area.width - 8) / sprite_width,
                    (image_area.height - 8) / sprite_height)
        render_size = (max(1, round(sprite_width * scale)),
                       max(1, round(sprite_height * scale)))
        rendered = pygame.transform.scale(sprite, render_size)
        sheet.blit(rendered, (image_area.centerx - rendered.get_width() // 2,
                              image_area.centery - rendered.get_height() // 2))
        label_surface = label_font.render(label, True, (235, 240, 248))
        if label_surface.get_width() > cell_width - 24:
            compact_font = pygame.font.SysFont("monospace", 12, bold=True)
            label_surface = compact_font.render(label, True, (235, 240, 248))
        sheet.blit(label_surface, (cell_x + (cell_width - label_surface.get_width()) // 2,
                                   cell_y + 151))

    output_path = Path(filename).expanduser().resolve()
    pygame.image.save(sheet, str(output_path))
    print(f"Saved sprite sheet to {output_path} ({len(sprites)} sprites)")


if args.print_map is not None:
    print_map_png(args.print_map)
if args.print_sprites is not None:
    print_sprite_sheet_png(args.print_sprites)
if args.print_map is not None or args.print_sprites is not None:
    pygame.quit()
    raise SystemExit(0)

MUSIC_SAMPLE_RATE = 22050
MUSIC_TEMPO = 120
MUSIC_BEAT_SECONDS = 60.0 / MUSIC_TEMPO
MUSIC_BAR_SECONDS = MUSIC_BEAT_SECONDS * 4
PLAYER_WEAPON_TEMPOS = (120, 126, 132)
PLAYER_WEAPON_COLORS = (
    PLASMA_EXPLOSION_TINT,
    (255, 58, 38),
    (70, 155, 255),
)
PLAYER_WEAPON_DAMAGE = (1, 2, 4)
ATTRACT_TEMPO = 180
ATTRACT_SECTION_BARS = 8
ATTRACT_MUSIC_SECTIONS = 6
ATTRACT_SECTION_SECONDS = ATTRACT_SECTION_BARS * 4 * 60.0 / ATTRACT_TEMPO
ATTRACT_SECTION_MS = ATTRACT_SECTION_SECONDS * 1000.0


def add_saw_note(buffer, start, duration, frequency, volume, end_frequency=None):
    """Mix a short, enveloped sawtooth voice into a mono float buffer."""
    first_sample = max(0, int(start * MUSIC_SAMPLE_RATE))
    sample_count = min(
        int(duration * MUSIC_SAMPLE_RATE), len(buffer) - first_sample
    )
    if sample_count <= 0:
        return

    attack_samples = max(1, int(0.006 * MUSIC_SAMPLE_RATE))
    release_samples = max(1, int(sample_count * 0.14))
    phase = 0.0
    phase_step = frequency / MUSIC_SAMPLE_RATE
    frequency_sweep = (
        (end_frequency - frequency) / sample_count
        if end_frequency is not None else 0.0
    )
    for index in range(sample_count):
        envelope = min(1.0, index / attack_samples)
        if index >= sample_count - release_samples:
            envelope *= (sample_count - index) / release_samples
        buffer[first_sample + index] += (phase * 2.0 - 1.0) * volume * envelope
        phase += phase_step
        phase -= int(phase)
        phase_step += frequency_sweep / MUSIC_SAMPLE_RATE


def midi_frequency(note):
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def make_drum_loop(beat_seconds=MUSIC_BEAT_SECONDS):
    """Create one repeating four-beat drum bar from synthesized saw waves."""
    loop = array("f", [0.0]) * int(beat_seconds * 4 * MUSIC_SAMPLE_RATE)
    beat = beat_seconds
    for beat_index in (0, 2):
        add_saw_note(loop, beat_index * beat, 0.22, 125, 0.30, 48)
    for beat_index in (1, 3):
        at = beat_index * beat
        add_saw_note(loop, at, 0.13, 205, 0.12, 150)
        add_saw_note(loop, at, 0.10, 390, 0.055, 310)
    for eighth in range(8):
        add_saw_note(loop, eighth * beat / 2, 0.035, 3600, 0.035, 2100)
    return loop


def make_music_buffer(seed, tempo=MUSIC_TEMPO):
    """Compose four evolving 16-bar sections entirely in memory."""
    beat_seconds = 60.0 / tempo
    bar_seconds = beat_seconds * 4
    rng = random.Random(seed ^ 0x4D55534943)
    keys = {
        "A minor": (45, (0, 2, 3, 5, 7, 8, 10)),
        "C major": (48, (0, 2, 4, 5, 7, 9, 11)),
        "D minor": (50, (0, 2, 3, 5, 7, 8, 10)),
        "E minor": (52, (0, 2, 3, 5, 7, 8, 10)),
        "G major": (55, (0, 2, 4, 5, 7, 9, 11)),
    }
    related_keys = {
        "A minor": ("C major", "D minor", "E minor"),
        "C major": ("A minor", "D minor", "G major"),
        "D minor": ("A minor", "C major", "G major"),
        "E minor": ("A minor", "C major", "G major"),
        "G major": ("C major", "D minor", "E minor"),
    }
    section_count = 4
    section_lengths = [rng.choice((2, 4, 8)) for _ in range(section_count)]
    total_bars = sum(section_lengths)
    samples_per_bar = int(bar_seconds * MUSIC_SAMPLE_RATE)
    mix = array("f", [0.0]) * (total_bars * samples_per_bar)
    drum_loop = make_drum_loop(beat_seconds)

    current_key = "A minor"
    melody_pattern = [rng.choice((0, 2, 3, 4, 6, 7, 9, None)) for _ in range(16)]
    bass_pattern = [rng.choice((0, 0, 2, 3, 4, 6)) for _ in range(4)]

    section_first_bar = 0
    for section, bars_per_section in enumerate(section_lengths):
        if section:
            change_key = rng.random() < 0.55
            change_pattern = rng.random() < 0.7
            if not change_key and not change_pattern:
                change_pattern = True
            if change_key:
                current_key = rng.choice(related_keys[current_key])
            if change_pattern:
                melody_pattern = [
                    rng.choice((0, 2, 3, 4, 6, 7, 9, None)) for _ in range(16)
                ]
                bass_pattern = [rng.choice((0, 0, 2, 3, 4, 6)) for _ in range(4)]

        root, scale = keys[current_key]
        for bar in range(bars_per_section):
            global_bar = section_first_bar + bar
            bar_start = global_bar * bar_seconds
            sample_start = global_bar * samples_per_bar
            # Repeat the same compact synthesized drum bar throughout the track.
            for sample_index, sample in enumerate(drum_loop):
                mix[sample_start + sample_index] += sample

            for beat_index, degree in enumerate(bass_pattern):
                note = root + scale[degree % 7] - 12
                if degree >= 7:
                    note += 12
                add_saw_note(
                    mix, bar_start + beat_index * beat_seconds,
                    beat_seconds * 0.82, midi_frequency(note), 0.14,
                )

            for eighth in range(8):
                degree = melody_pattern[(bar % 2) * 8 + eighth]
                if degree is None:
                    continue
                note = root + scale[degree % 7] + 12
                if degree >= 7:
                    note += 12
                add_saw_note(
                    mix, bar_start + eighth * beat_seconds / 2,
                    beat_seconds * 0.43, midi_frequency(note), 0.075,
                )
        section_first_bar += bars_per_section

    pcm = array("h")
    for sample in mix:
        pcm.append(int(max(-1.0, min(1.0, sample)) * 32767))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


def make_victory_music():
    """Compose a bright, major-key arcade victory loop."""
    tempo = VICTORY_MUSIC_TEMPO
    beat = 60.0 / tempo
    bar_seconds = beat * 4
    progression = (
        (48, (60, 64, 67)),  # C major
        (43, (55, 59, 62)),  # G major
        (45, (57, 60, 64)),  # A minor
        (41, (53, 57, 60)),  # F major
    ) * 2
    mix = array("f", [0.0]) * int(bar_seconds * len(progression) * MUSIC_SAMPLE_RATE)
    drums = make_drum_loop(beat)
    for bar_index, (bass_note, chord) in enumerate(progression):
        bar_start = bar_index * bar_seconds
        first_sample = int(bar_start * MUSIC_SAMPLE_RATE)
        for sample_index, sample in enumerate(drums):
            mix[first_sample + sample_index] += sample * 0.72
        for beat_index in range(4):
            add_saw_note(
                mix, bar_start + beat_index * beat, beat * 0.72,
                midi_frequency(bass_note), 0.115,
            )
        for beat_index in (0, 2):
            for note in chord:
                add_saw_note(
                    mix, bar_start + beat_index * beat, beat * 0.72,
                    midi_frequency(note + 12), 0.055,
                )
        arpeggio = (chord[0] + 24, chord[1] + 24, chord[2] + 24,
                    chord[1] + 24, chord[2] + 24, chord[1] + 24,
                    chord[0] + 24, chord[1] + 24)
        for eighth, note in enumerate(arpeggio):
            add_saw_note(
                mix, bar_start + eighth * beat / 2, beat * 0.36,
                midi_frequency(note), 0.075,
            )
    pcm = array("h")
    for sample in mix:
        pcm.append(int(math.tanh(sample * 1.55) * 30000))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


def make_rock_music_buffer(seed):
    """Compose a random minor-key rock progression for each guide screen."""
    tempo = ATTRACT_TEMPO
    beat = 60.0 / tempo
    bar_seconds = beat * 4
    rng = random.Random(seed ^ 0x524F434B)
    key_root = rng.choice((38, 40, 43, 45))  # D, E, G, or A minor
    tonic = (key_root, 3)
    mediant = (key_root + 3, 4)
    subdominant = (key_root + 5, 3)
    dominant = (key_root + 7, 3)
    submediant = (key_root + 8, 4)
    subtonic = (key_root + 10, 4)

    progression = []
    section_gains = []
    for _ in range(ATTRACT_MUSIC_SECTIONS):
        phrase = (
            rng.choice((tonic, mediant, submediant)),
            rng.choice((mediant, subdominant, submediant)),
            rng.choice((dominant, subtonic, subdominant)),
            rng.choice((tonic, mediant, submediant)),
        )
        section_index = len(section_gains)
        progression.extend((root, third, section_index)
                           for root, third in phrase * 2)
        section_gains.append(rng.uniform(0.92, 1.22))
    mix = array("f", [0.0]) * int(bar_seconds * len(progression) * MUSIC_SAMPLE_RATE)

    def add_noise(start, duration, volume, decay):
        first = int(start * MUSIC_SAMPLE_RATE)
        count = min(int(duration * MUSIC_SAMPLE_RATE), len(mix) - first)
        for index in range(max(0, count)):
            progress = index / max(1, count)
            envelope = math.exp(-decay * progress) * min(1.0, index / 35.0)
            mix[first + index] += rng.uniform(-1.0, 1.0) * volume * envelope

    for bar_index, (root, third, section_index) in enumerate(progression):
        bar_start = bar_index * bar_seconds
        section_gain = section_gains[section_index]

        # Chord tones are struck together on the strong beats.
        for beat_index in (0, 2):
            chord_start = bar_start + beat_index * beat
            for note, volume in ((root + 24, 0.13), (root + 24 + third, 0.085),
                                 (root + 31, 0.105), (root + 36, 0.07)):
                add_saw_note(mix, chord_start, beat * 1.65,
                             midi_frequency(note), volume * section_gain)
            add_saw_note(mix, chord_start, beat * 1.7,
                         midi_frequency(root), 0.17 * section_gain)

        chord_tones = (root + 24, root + 24 + third, root + 31,
                       root + 36, root + 43)
        arp_patterns = (
            (0, 1, 2, 3, 2, 1, 2, 4),
            (0, 2, 1, 3, 2, 0, 2, 4),
            (2, 1, 0, 2, 3, 2, 1, 4),
            (0, 1, 2, 4, 3, 2, 1, 4),
        )
        arpeggio = tuple(chord_tones[index] for index in rng.choice(arp_patterns))
        for eighth, note in enumerate(arpeggio):
            add_saw_note(
                mix, bar_start + eighth * beat / 2, beat * 0.42,
                midi_frequency(note), 0.09 * section_gain,
            )

        if bar_index > 0 and bar_index % ATTRACT_SECTION_BARS == 0:
            add_noise(bar_start, 0.65, 0.24, 2.0)

        # Driving kick, backbeat snare, and steady eighth-note hats.
        for beat_index in (0, 2):
            add_saw_note(mix, bar_start + beat_index * beat, 0.22,
                         118.0, 0.44, 42.0)
        for beat_index in (1, 3):
            snare_start = bar_start + beat_index * beat
            add_noise(snare_start, 0.16, 0.28, 8.0)
            add_saw_note(mix, snare_start, 0.12, 205.0, 0.13, 105.0)
        for eighth in range(8):
            add_noise(bar_start + eighth * beat / 2, 0.035, 0.09, 10.0)

    pcm = array("h")
    for sample in mix:
        # Gentle clipping gives the saw chords a compact, arcade-rock edge.
        pcm.append(int(math.tanh(sample * 1.7) * 30000))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


def make_game_over_music():
    """Compose a fixed, looping four-bar sad end-credits cue in memory."""
    tempo = 76
    bar_seconds = 60.0 / tempo * 4
    total_seconds = bar_seconds * 4
    mix = array("f", [0.0]) * int(total_seconds * MUSIC_SAMPLE_RATE)
    progression = (
        ((45, 52, 57, 60), (69, 67)),  # Am7
        ((41, 48, 53, 57), (65, 64)),  # Fmaj7
        ((38, 45, 50, 53), (62, 60)),  # Dm7
        ((40, 47, 52, 56), (59, 57)),  # E7
    )

    def add_soft_note(start, duration, note, volume):
        first = int(start * MUSIC_SAMPLE_RATE)
        count = min(int(duration * MUSIC_SAMPLE_RATE), len(mix) - first)
        frequency = midi_frequency(note)
        phase = 0.0
        for index in range(max(0, count)):
            time = index / MUSIC_SAMPLE_RATE
            attack = min(1.0, time / 0.16)
            release = min(1.0, max(0.0, (duration - time) / 0.35))
            envelope = attack * release
            # A soft sine with a faint triangle harmonic keeps the cue gentle
            # while retaining the game's simple synthesized character.
            sine = math.sin(phase * math.tau)
            triangle = 2.0 * abs(2.0 * (phase - math.floor(phase + 0.5))) - 1.0
            mix[first + index] += (sine * 0.82 + triangle * 0.18) * volume * envelope
            phase = (phase + frequency / MUSIC_SAMPLE_RATE) % 1.0

    for bar, (chord, melody_pair) in enumerate(progression):
        start = bar * bar_seconds
        for voice, note in enumerate(chord):
            add_soft_note(start, bar_seconds * 0.94, note, 0.075 if voice == 0 else 0.035)
        for beat, note in enumerate(melody_pair):
            add_soft_note(start + (beat * 2 + 1) * (bar_seconds / 4), 0.9, note, 0.055)

    pcm = array("h")
    for sample in mix:
        pcm.append(int(max(-1.0, min(1.0, sample)) * 32767))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


def make_start_sfx():
    """Synthesize a brief, voice-like two-syllable arcade start cue."""
    sample_rate = MUSIC_SAMPLE_RATE
    duration = 0.78
    sample_count = int(duration * sample_rate)
    rng = random.Random(WORLD_SEED ^ 0x4C455453474F)
    pcm = array("h")
    phase = 0.0
    for index in range(sample_count):
        time = index / sample_rate
        if time < 0.25:
            local = time / 0.25
            pitch = 188.0 - 34.0 * local
            envelope = min(1.0, time / 0.018) * min(1.0, (0.27 - time) / 0.055)
            formants = ((520.0, 190.0), (1780.0, 320.0), (2650.0, 480.0))
        elif 0.30 <= time < duration:
            local = (time - 0.30) / (duration - 0.30)
            pitch = 150.0 + 52.0 * local
            envelope = min(1.0, local / 0.045) * min(1.0, (1.0 - local) / 0.14)
            formants = ((480.0 - 105.0 * local, 190.0),
                        (980.0 - 170.0 * local, 280.0), (2520.0, 440.0))
        else:
            pitch = 150.0
            envelope = 0.0
            formants = ()

        phase = (phase + pitch / sample_rate) % 1.0
        voice = 0.0
        for harmonic in range(1, 20):
            frequency = pitch * harmonic
            spectral_weight = sum(
                math.exp(-0.5 * ((frequency - center) / width) ** 2)
                for center, width in formants
            )
            voice += math.sin(math.tau * phase * harmonic) * spectral_weight / harmonic
        voice *= 0.25 * envelope

        consonant = 0.0
        if 0.17 <= time < 0.29:
            consonant = rng.uniform(-1.0, 1.0) * (0.20 * (time - 0.17) / 0.12)
        elif 0.30 <= time < 0.35:
            consonant = rng.uniform(-1.0, 1.0) * (0.12 * (0.35 - time) / 0.05)
        value = max(-1.0, min(1.0, voice + consonant))
        pcm.append(int(value * 23500))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


def make_arcade_sfx(kind):
    """Synthesize a short, quantized arcade effect without writing a file."""
    sample_rate = MUSIC_SAMPLE_RATE
    profiles = {
        "fire": (0.19, 880.0, 125.0),
        "quad_damage_fire": (0.28, 165.0, 72.0),
        "quad_damage_hit": (0.46, 125.0, 34.0),
        "wall": (0.34, 150.0, 38.0),
        "enemy_hit": (0.28, 660.0, 390.0),
        "enemy_death": (0.62, 260.0, 48.0),
        "player_hit": (0.42, 340.0, 68.0),
        "triangle_spawn": (0.34, 1550.0, 2450.0),
        "violet_triangle_spawn": (0.38, 1680.0, 2600.0),
        "sphere_spawn": (0.28, 520.0, 210.0),
        "rectangle_spawn": (0.42, 1450.0, 180.0),
        "enemy_shoot": (0.13, 720.0, 260.0),
        "enemy_plasma_explosion": (0.48, 190.0, 52.0),
        "blue_cannon_fire": (0.24, 430.0, 105.0),
        "blue_plasma_hit": (0.58, 150.0, 38.0),
        "armor_pickup": (0.55, 620.0, 1240.0),
        "health_pickup": (0.68, 520.0, 1560.0),
        "booster_pickup": (0.88, 520.0, 1560.0),
        "quad_damage_pickup": (0.96, 115.0, 390.0),
        "super_speed_pickup": (0.62, 980.0, 2100.0),
        "weapon_level_up": (0.72, 520.0, 1560.0),
        "sphere_beam": (0.82, 660.0, 1980.0),
        "shortcut_break": (0.72, 260.0, 42.0),
    }
    duration, start_frequency, end_frequency = profiles[kind]
    sample_count = int(duration * sample_rate)
    rng = random.Random(0x5A17 + tuple(profiles).index(kind))
    pcm = array("h")
    phase_a = phase_b = 0.0
    filtered_noise = 0.0

    for index in range(sample_count):
        time = index / sample_rate
        progress = time / duration
        frequency = start_frequency * (end_frequency / start_frequency) ** progress
        phase_a = (phase_a + frequency / sample_rate) % 1.0
        pulse_a = 1.0 if phase_a < 0.5 else -1.0
        noise = rng.uniform(-1.0, 1.0)
        filtered_noise += 0.12 * (noise - filtered_noise)

        if kind == "fire":
            envelope = (1.0 - progress) ** 1.5
            value = 0.24 * pulse_a + 0.24 * noise * math.exp(-time * 22.0)
        elif kind == "quad_damage_fire":
            phase_b = (phase_b + frequency * 0.493 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = (1.0 - progress) ** 0.65
            value = 0.48 * pulse_a + 0.40 * pulse_b + 0.42 * filtered_noise
        elif kind == "quad_damage_hit":
            phase_b = (phase_b + frequency * 0.503 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 5.0) * min(1.0, time * 80.0)
            value = 0.45 * pulse_a + 0.36 * pulse_b + 0.70 * filtered_noise
        elif kind == "wall":
            envelope = math.exp(-time * 7.5) * min(1.0, time * 90.0)
            value = 0.24 * pulse_a + 0.75 * filtered_noise
        elif kind == "enemy_hit":
            phase_b = (phase_b + (start_frequency * 1.42) / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 9.0) * min(1.0, time * 120.0)
            value = 0.20 * pulse_a + 0.13 * pulse_b + 0.22 * noise * math.exp(-time * 25.0)
        elif kind == "player_hit":
            phase_b = (phase_b + (frequency * 1.19) / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 5.5) * min(1.0, time * 100.0)
            value = 0.42 * pulse_a + 0.38 * pulse_b + 0.55 * filtered_noise
        elif kind == "triangle_spawn":
            phase_b = (phase_b + frequency * 1.51 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = (1.0 - progress) ** 0.7
            value = 0.58 * pulse_a + 0.24 * pulse_b + 0.12 * noise
        elif kind == "violet_triangle_spawn":
            phase_b = (phase_b + frequency * 2.03 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = (1.0 - progress) ** 0.62
            value = 0.42 * pulse_a + 0.38 * pulse_b + 0.20 * math.sin(phase_a * math.tau)
        elif kind == "sphere_spawn":
            phase_b = (phase_b + frequency * 0.503 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 5.2) * min(1.0, time * 80.0)
            value = 0.46 * pulse_a + 0.30 * pulse_b + 0.16 * filtered_noise
        elif kind == "rectangle_spawn":
            phase_b = (phase_b + frequency * 1.37 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = (1.0 - progress) ** 0.45
            value = 0.62 * pulse_a + 0.52 * pulse_b + 0.38 * noise
        elif kind == "enemy_shoot":
            envelope = (1.0 - progress) ** 2.0
            value = 0.38 * pulse_a + 0.16 * noise * math.exp(-time * 20.0)
        elif kind == "blue_cannon_fire":
            phase_b = (phase_b + frequency * 0.51 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = (1.0 - progress) ** 1.35
            value = 0.48 * pulse_a + 0.34 * pulse_b + 0.42 * filtered_noise
        elif kind == "blue_plasma_hit":
            phase_b = (phase_b + frequency * 0.47 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 4.2) * min(1.0, time * 45.0)
            value = 0.38 * pulse_a + 0.34 * pulse_b + 0.68 * filtered_noise
        elif kind == "armor_pickup":
            phase_b = (phase_b + frequency * 1.5 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = (1.0 - progress) ** 1.2
            value = 0.42 * math.sin(phase_a * math.tau) + 0.24 * pulse_b
        elif kind == "health_pickup":
            phase_b = (phase_b + frequency * 1.25 / sample_rate) % 1.0
            envelope = (1.0 - progress) ** 1.1
            value = (0.40 * math.sin(phase_a * math.tau)
                     + 0.20 * math.sin(phase_b * math.tau)
                     + 0.12 * pulse_a)
        elif kind == "booster_pickup":
            phase_b = (phase_b + frequency * 1.5 / sample_rate) % 1.0
            envelope = (1.0 - progress) ** 0.72
            value = (0.38 * math.sin(phase_a * math.tau)
                     + 0.34 * math.sin(phase_b * math.tau)
                     + 0.18 * pulse_a)
        elif kind == "quad_damage_pickup":
            phase_b = (phase_b + frequency * 0.503 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 3.0) * min(1.0, time * 60.0)
            value = (0.62 * pulse_a + 0.48 * pulse_b
                     + 0.34 * filtered_noise)
        elif kind == "super_speed_pickup":
            phase_b = (phase_b + frequency * 1.5 / sample_rate) % 1.0
            envelope = (1.0 - progress) ** 0.8
            value = (0.34 * math.sin(phase_a * math.tau)
                     + 0.28 * math.sin(phase_b * math.tau)
                     + 0.20 * pulse_a)
        elif kind == "weapon_level_up":
            phase_b = (phase_b + frequency * 1.5 / sample_rate) % 1.0
            envelope = (1.0 - progress) ** 0.8
            value = (0.38 * math.sin(phase_a * math.tau)
                     + 0.28 * math.sin(phase_b * math.tau)
                     + 0.18 * pulse_a)
        elif kind == "sphere_beam":
            phase_b = (phase_b + frequency * 1.5 / sample_rate) % 1.0
            envelope = min(1.0, time * 32.0) * (1.0 - progress) ** 0.8
            value = (0.46 * math.sin(phase_a * math.tau)
                     + 0.24 * math.sin(phase_b * math.tau)
                     + 0.12 * pulse_a)
        elif kind == "shortcut_break":
            phase_b = (phase_b + frequency * 0.43 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 4.2) * min(1.0, time * 90.0)
            value = (0.48 * pulse_a + 0.32 * pulse_b
                     + 0.72 * filtered_noise)
        elif kind == "enemy_plasma_explosion":
            phase_b = (phase_b + frequency * 0.57 / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 5.8) * min(1.0, time * 55.0)
            value = 0.30 * pulse_a + 0.32 * pulse_b + 0.55 * filtered_noise
        else:
            phase_b = (phase_b + (frequency * 0.56) / sample_rate) % 1.0
            pulse_b = 1.0 if phase_b < 0.5 else -1.0
            envelope = math.exp(-time * 4.6) * min(1.0, time * 70.0)
            impact_crackle = noise * math.exp(-time * 18.0)
            value = 0.27 * pulse_a + 0.24 * pulse_b + 0.62 * filtered_noise + 0.30 * impact_crackle

        # Quantize to an 8-bit-like amplitude before storing as mixer PCM.
        value = max(-1.0, min(1.0, value * envelope))
        pcm.append(int(round(value * 127) * (32767 / 127)))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


def make_menu_sfx(confirmed=False):
    """Create a bright two-note navigation pling or a three-note confirm cue."""
    sample_rate = MUSIC_SAMPLE_RATE
    notes = ((0.0, 740.0), (0.075, 1110.0)) if not confirmed else (
        (0.0, 620.0), (0.085, 930.0), (0.17, 1395.0)
    )
    duration = 0.30 if confirmed else 0.22
    pcm = array("h")
    for index in range(int(duration * sample_rate)):
        time = index / sample_rate
        value = 0.0
        for start, frequency in notes:
            note_time = time - start
            if 0.0 <= note_time < 0.15:
                envelope = min(1.0, note_time / 0.004) * math.exp(-note_time * 20.0)
                phase = math.tau * frequency * note_time
                value += (math.sin(phase) + 0.22 * math.sin(phase * 2.01)) * envelope
        pcm.append(int(max(-1.0, min(1.0, value * 0.22)) * 32767))
    return pygame.mixer.Sound(buffer=pcm.tobytes())


if pygame.mixer.get_init():
    pygame.mixer.set_num_channels(16)
    arcade_sfx = {
        kind: make_arcade_sfx(kind)
        for kind in ("fire", "quad_damage_fire", "quad_damage_hit", "wall",
                     "enemy_hit", "enemy_death", "player_hit",
                     "triangle_spawn", "violet_triangle_spawn", "sphere_spawn",
                     "rectangle_spawn", "enemy_shoot",
                     "enemy_plasma_explosion", "blue_cannon_fire", "blue_plasma_hit",
                     "armor_pickup", "health_pickup", "booster_pickup",
                     "quad_damage_pickup",
                     "super_speed_pickup", "weapon_level_up",
                     "sphere_beam", "shortcut_break")
    }
    arcade_sfx["start"] = make_start_sfx()
    arcade_sfx["menu_move"] = make_menu_sfx()
    arcade_sfx["menu_select"] = make_menu_sfx(confirmed=True)
    game_over_music = make_game_over_music()
else:
    arcade_sfx = {}
    game_over_music = None


def play_sfx(kind):
    sound = arcade_sfx.get(kind)
    if sound is not None:
        sound.play()


def play_weapon_music():
    if boss_room_active:
        return
    if pygame.mixer.get_init() and player_weapon_music:
        channel = pygame.mixer.Channel(0)
        channel.stop()
        music_set = (player_super_speed_music
                     if super_speed_timer > 0.0 and player_super_speed_music
                     else player_weapon_music)
        channel.play(music_set[player_weapon_level], loops=-1)


def play_boss_music():
    if pygame.mixer.get_init() and boss_music is not None:
        channel = pygame.mixer.Channel(0)
        channel.stop()
        channel.play(boss_music, loops=-1)


def play_victory_music():
    global victory_music_started
    if pygame.mixer.get_init() and victory_music is not None:
        channel = pygame.mixer.Channel(0)
        channel.stop()
        channel.play(victory_music, loops=-1)
        victory_music_started = pygame.time.get_ticks()


def spawn_boss_wave(stage):
    """Spawn one of the room's three kill-gated enemy waves."""
    global boss_wave_stage
    boss_wave_stage = stage
    rng = random.Random(WORLD_SEED ^ (0x57415645 + stage * 0x10101))
    room_cells = [
        (cell_x, cell_y)
        for cell_y in range(BOSS_ROOM_TOP + 1, BOSS_ROOM_BOTTOM)
        for cell_x in range(BOSS_ROOM_LEFT + 1, BOSS_ROOM_RIGHT)
        if world_block(cell_x, cell_y) == 0
    ]
    if stage == 3:
        center_cell = min(
            room_cells,
            key=lambda cell: abs(cell[0] - (BOSS_CORE_LEFT + 0.5))
            + abs(cell[1] - (BOSS_CORE_TOP + 0.5)),
        )
        boss = make_enemy_record(
            *center_cell, "rectangle", (245, 38, 65), hit_multiplier=1.0
        )
        boss["boss"] = True
        boss["boss_wave"] = stage
        boss["shot_timer"] = 0.65
        boss["plasma_cycle"] = 0
        enemies.append(boss)
        return

    spawn_count = 10 if stage == 1 else 5
    color = (245, 64, 52) if stage == 1 else (54, 142, 255)
    blue_cannon = stage == 2
    for cell_x, cell_y in rng.sample(room_cells, min(spawn_count, len(room_cells))):
        enemy = make_enemy_record(
            cell_x, cell_y, "rectangle", color,
            hit_multiplier=1.0, blue_cannon=blue_cannon,
        )
        enemy["boss_wave"] = stage
        enemies.append(enemy)


def advance_boss_wave():
    """Start the next wave only after every member of the current one is dead."""
    if boss_wave_stage not in (1, 2):
        return
    if any(enemy.get("boss_wave") == boss_wave_stage for enemy in enemies):
        return
    spawn_boss_wave(boss_wave_stage + 1)


def start_boss_room():
    """Lock the four room exits, populate the glass cell, and start its music."""
    global boss_room_active, boss_spheres, boss_triangle_spawn_timer
    global boss_battle_complete, boss_cage_destroyed, boss_cage_destroy_timer
    if boss_room_active:
        return
    boss_room_active = True
    boss_battle_complete = False
    boss_cage_destroyed = False
    boss_cage_destroy_timer = 0.0
    rng = random.Random(WORLD_SEED ^ 0xB055F16A)
    sphere_count = rng.randint(3, 6)
    pinks = ((255, 82, 181), (255, 112, 205), (238, 58, 157),
             (255, 145, 220), (245, 76, 190), (255, 96, 165))
    minimum_x = (BOSS_CORE_LEFT + 0.25) * TILE_SIZE
    maximum_x = (BOSS_CORE_LEFT + 1.75) * TILE_SIZE
    minimum_y = (BOSS_CORE_TOP + 0.25) * TILE_SIZE
    maximum_y = (BOSS_CORE_TOP + 1.75) * TILE_SIZE
    boss_spheres = []
    for index in range(sphere_count):
        animation_phase = (
            world_hash(index + 0x535048, sphere_count - index - 0x4552)
            / (WORLD_MASK + 1) * math.tau
        )
        boss_spheres.append({
            "x": rng.uniform(minimum_x, maximum_x),
            "y": rng.uniform(minimum_y, maximum_y),
            "color": pinks[index],
            "virtual": False,
            "wander_rng": random.Random(rng.getrandbits(64)),
            "wander_target": None,
            "wander_speed": rng.uniform(22.0, 44.0),
            "orbit_phase": rng.random() * math.tau,
            "animation_phase": animation_phase,
            "swarm_timer": 0.0,
            "swarm_path": [],
            "swarm_path_index": 1,
            "beam_state": None,
            "beam_timer": 0.0,
            "beam_height": 0.0,
        })
    boss_triangle_spawn_timer = random.uniform(7.0, 12.0)
    spawn_boss_wave(1)
    play_boss_music()


def finish_boss_battle():
    """Open the room and begin the cage-break and sphere-release sequence."""
    global boss_battle_complete, boss_wave_stage, boss_cage_destroy_timer
    global boss_cage_destroyed, boss_cage_blasts
    if boss_battle_complete:
        return
    boss_battle_complete = True
    boss_wave_stage = 4
    boss_cage_destroyed = False
    boss_cage_destroy_timer = 3.4
    enemies.clear()
    hostile_projectiles.clear()
    rng = random.Random(WORLD_SEED ^ 0x524553435545)
    cage_min_x = BOSS_CORE_LEFT * TILE_SIZE
    cage_min_y = BOSS_CORE_TOP * TILE_SIZE
    cage_max_x = (BOSS_CORE_LEFT + 2) * TILE_SIZE
    cage_max_y = (BOSS_CORE_TOP + 2) * TILE_SIZE
    explosion_colors = (
        (255, 70, 130), (255, 145, 210), (255, 230, 250), (255, 190, 70),
    )
    boss_cage_blasts.clear()
    for index in range(28):
        side = index % 4
        if side == 0:
            blast_x, blast_y = cage_min_x, rng.uniform(cage_min_y, cage_max_y)
        elif side == 1:
            blast_x, blast_y = cage_max_x, rng.uniform(cage_min_y, cage_max_y)
        elif side == 2:
            blast_x, blast_y = rng.uniform(cage_min_x, cage_max_x), cage_min_y
        else:
            blast_x, blast_y = rng.uniform(cage_min_x, cage_max_x), cage_max_y
        boss_cage_blasts.append({
            "x": blast_x,
            "y": blast_y,
            "explosion": PLASMA_EXPLOSION_DURATION,
            "delay": rng.uniform(0.0, 2.45),
            "blue_cannon": False,
            "plasma_color": rng.choice(explosion_colors),
        })
    play_victory_music()


def update_boss_victory_fx(delta_time):
    global boss_cage_destroy_timer, boss_cage_destroyed
    if not boss_battle_complete or boss_cage_destroyed:
        return
    boss_cage_destroy_timer = max(0.0, boss_cage_destroy_timer - delta_time)
    survivors = []
    for blast in boss_cage_blasts:
        if blast["delay"] > 0.0:
            blast["delay"] = max(0.0, blast["delay"] - delta_time)
        else:
            blast["explosion"] -= delta_time
        if blast["delay"] > 0.0 or blast["explosion"] > 0.0:
            survivors.append(blast)
    boss_cage_blasts[:] = survivors
    if boss_cage_destroy_timer <= 0.0:
        boss_cage_destroyed = True
        boss_cage_blasts.clear()
        for sphere in boss_spheres:
            sphere["swarm_path"] = []
            sphere["swarm_path_index"] = 1
            sphere["swarm_timer"] = 0.0


def update_boss_spheres(delta_time):
    """Make the harmless pink spheres drift randomly within their glass cell."""
    global victory_screen_active
    if not boss_room_active:
        return
    if boss_battle_complete and boss_cage_destroyed:
        player_cell = (math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE))
        for sphere in boss_spheres:
            if sphere["beam_state"] == "gone":
                continue
            if sphere["beam_state"] == "beaming":
                sphere["beam_timer"] -= delta_time
                progress = 1.0 - max(0.0, sphere["beam_timer"]) / 1.15
                sphere["beam_height"] = max(0.0, progress) * TILE_SIZE * 1.8
                if sphere["beam_timer"] <= 0.0:
                    sphere["beam_state"] = "gone"
                continue
            sphere_cell = (math.floor(sphere["x"] / TILE_SIZE),
                           math.floor(sphere["y"] / TILE_SIZE))
            if sphere_cell == BOSS_ESCAPE_PORTAL_CELL:
                sphere["beam_state"] = "beaming"
                sphere["beam_timer"] = 1.15
                sphere["beam_height"] = 0.0
                play_sfx("sphere_beam")
                continue
            sphere["orbit_phase"] = (sphere["orbit_phase"] + delta_time * 0.65) % math.tau
            sphere["swarm_timer"] -= delta_time
            path = sphere["swarm_path"]
            path_index = sphere["swarm_path_index"]
            if sphere["swarm_timer"] <= 0.0 or path_index >= len(path):
                current = (math.floor(sphere["x"] / TILE_SIZE),
                           math.floor(sphere["y"] / TILE_SIZE))
                if player_in_open_space:
                    desired = BOSS_ESCAPE_PORTAL_CELL
                else:
                    candidates = [
                        (player_cell[0] + offset_x, player_cell[1] + offset_y)
                        for offset_y in range(-4, 5)
                        for offset_x in range(-4, 5)
                        if 1.0 <= math.hypot(offset_x, offset_y) <= 4.0
                        and world_block(player_cell[0] + offset_x,
                                        player_cell[1] + offset_y) == 0
                    ]
                    desired = min(
                        candidates,
                        key=lambda cell: abs((
                            math.atan2(cell[1] - player_cell[1],
                                       cell[0] - player_cell[0])
                            - sphere["orbit_phase"] + math.pi
                        ) % math.tau - math.pi),
                    ) if candidates else current
                new_path = find_maze_path(current, desired, 64)
                sphere["swarm_path"] = new_path or []
                sphere["swarm_path_index"] = 1
                sphere["swarm_timer"] = 0.8
                path = sphere["swarm_path"]
                path_index = sphere["swarm_path_index"]
            if path_index < len(path):
                target_x = (path[path_index][0] + 0.5) * TILE_SIZE
                target_y = (path[path_index][1] + 0.5) * TILE_SIZE
                dx, dy = target_x - sphere["x"], target_y - sphere["y"]
                distance = math.hypot(dx, dy)
                step = min(distance, 100.0 * delta_time)
                if distance > 0.0 and step > 0.0:
                    sphere["x"] += dx / distance * step
                    sphere["y"] += dy / distance * step
                if distance <= step + 1.0:
                    sphere["swarm_path_index"] += 1
        if (player_in_open_space and boss_spheres
                and all(sphere["beam_state"] == "gone" for sphere in boss_spheres)):
            victory_screen_active = True
        return
    minimum_x = (BOSS_CORE_LEFT + 0.25) * TILE_SIZE
    maximum_x = (BOSS_CORE_LEFT + 1.75) * TILE_SIZE
    minimum_y = (BOSS_CORE_TOP + 0.25) * TILE_SIZE
    maximum_y = (BOSS_CORE_TOP + 1.75) * TILE_SIZE
    for sphere in boss_spheres:
        rng = sphere["wander_rng"]
        target = sphere.get("wander_target")
        if target is None or math.hypot(target[0] - sphere["x"],
                                        target[1] - sphere["y"]) < 5.0:
            target = (rng.uniform(minimum_x, maximum_x),
                      rng.uniform(minimum_y, maximum_y))
            sphere["wander_target"] = target
        dx, dy = target[0] - sphere["x"], target[1] - sphere["y"]
        distance = math.hypot(dx, dy)
        step = min(distance, sphere["wander_speed"] * delta_time)
        if distance > 0.0 and step > 0.0:
            sphere["x"] += dx / distance * step
            sphere["y"] += dy / distance * step


if pygame.mixer.get_init():
    player_weapon_music = tuple(
        make_music_buffer(WORLD_SEED, tempo)
        for tempo in PLAYER_WEAPON_TEMPOS
    )
    player_super_speed_music = tuple(
        make_music_buffer(WORLD_SEED, round(tempo * 1.20))
        for tempo in PLAYER_WEAPON_TEMPOS
    )
    generated_music = player_weapon_music[0]
    boss_music = make_music_buffer(WORLD_SEED ^ 0xB055F16A, tempo=156)
    victory_music = make_victory_music()
    attract_music_seed = random.SystemRandom().getrandbits(64)
    attract_music = make_rock_music_buffer(attract_music_seed)
    attract_music.set_volume(0.42)
    pygame.mixer.Channel(0).play(generated_music, loops=-1)
    title_music_started = pygame.time.get_ticks()
else:
    player_weapon_music = ()
    player_super_speed_music = ()
    generated_music = None
    boss_music = None
    victory_music = None
    attract_music = None
    title_music_started = pygame.time.get_ticks()


def make_game_over_title():
    """Make a chunky red title with a dark, shaded drop shadow."""
    font = pygame.font.SysFont("monospace", max(18, HEIGHT // 16), bold=True)
    size = font.size("GAME OVER")

    def pixelated(color):
        text = font.render("GAME OVER", False, color)
        reduced = pygame.transform.scale(text, (max(1, size[0] // 2), max(1, size[1] // 2)))
        return pygame.transform.scale(reduced, (size[0] * 2, size[1] * 2))

    shadow = pixelated((75, 0, 14))
    red = pixelated((255, 38, 30))
    highlight = pixelated((255, 115, 60))
    title = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    x = (WIDTH - red.get_width()) // 2
    y = (HEIGHT - red.get_height()) // 2
    title.blit(shadow, (x + 6, y + 8))
    title.blit(highlight, (x, y - 2))
    title.blit(red, (x, y))
    return title


def make_start_title():
    """Make the start logo with the same chunky pixel shading as game over."""
    text = "SHAP3D"
    font = pygame.font.SysFont("monospace", max(24, HEIGHT // 12), bold=True)
    size = font.size(text)

    def pixelated(color):
        rendered = font.render(text, False, color)
        reduced = pygame.transform.scale(
            rendered, (max(1, size[0] // 2), max(1, size[1] // 2))
        )
        return pygame.transform.scale(reduced, (size[0] * 2, size[1] * 2))

    shadow = pixelated((75, 0, 14))
    red = pixelated((255, 38, 30))
    highlight = pixelated((255, 115, 60))
    title = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    x = (WIDTH - red.get_width()) // 2
    y = int(HEIGHT * 0.18)
    title.blit(shadow, (x + 6, y + 8))
    title.blit(highlight, (x, y - 2))
    title.blit(red, (x, y))
    return title


def make_start_prompt():
    font = pygame.font.SysFont("monospace", max(15, HEIGHT // 26), bold=True)
    text = font.render("press space to start", False, (245, 245, 245))
    return pygame.transform.scale(text, (text.get_width() * 2, text.get_height() * 2))


def draw_victory_screen(target):
    target.fill((3, 5, 18))
    twinkle = 0.72 + 0.28 * math.sin(pygame.time.get_ticks() * 0.002)
    for star_angle, star_y, color, size in SPACE_STARS:
        star_x = int((star_angle % math.tau) / math.tau * WIDTH)
        tint = tuple(int(channel * twinkle) for channel in color)
        pygame.draw.rect(target, tint, (star_x, star_y, size, size))
    title_font = pygame.font.SysFont("monospace", max(42, HEIGHT // 7), bold=True)
    title = title_font.render("VICTORY", False, (125, 255, 185))
    title_x = (WIDTH - title.get_width()) // 2
    title_y = int(HEIGHT * 0.32)
    target.blit(title, (title_x + 4, title_y + 5))
    target.blit(title_font.render("VICTORY", False, (255, 255, 255)),
                (title_x, title_y))
    subtitle_font = pygame.font.SysFont("monospace", max(15, HEIGHT // 28), bold=True)
    subtitle = subtitle_font.render("THE SPHERES ARE HOME", True, (255, 145, 215))
    target.blit(subtitle, ((WIDTH - subtitle.get_width()) // 2,
                           int(HEIGHT * 0.51)))
    prompt_font = pygame.font.SysFont("monospace", max(13, HEIGHT // 38), bold=True)
    prompt = prompt_font.render("SPACE: RETURN TO TITLE", True, (220, 230, 245))
    beat_ms = 60000.0 / VICTORY_MUSIC_TEMPO
    beat_phase = (pygame.time.get_ticks() - victory_music_started) % beat_ms
    if beat_phase < beat_ms * 0.68:
        target.blit(prompt, ((WIDTH - prompt.get_width()) // 2,
                             int(HEIGHT * 0.82)))


ATTRACT_CARDS = (
    {
        "name": "WASD WANDERER",
        "kind": "PILOT CONTROLS",
        "sprite": "controls",
        "lines": (
            "W/S move. A/D strafe.",
            "J/K turn. SPACE fires.",
            "SHIFT sprints.",
            "F fires a marker.",
            "ESC pauses the game, but not the enemies hunger.",
        ),
    },
    {
        "name": "VOID ORBS",
        "kind": "SPHERE CLASS",
        "sprite": "sphere",
        "lines": (
            "Appear in groups.",
            "Patient hunters with a talent",
            "for appearing in the wrong place.",
            "Deeply stubborn, and never pink.",
            "They hate humans, but not as much as the other spheres.",
        ),
    },
    {
        "name": "PINK COMET",
        "kind": "SPHERE CLASS",
        "sprite": "friendly_sphere",
        "lines": (
            "A pacifist, not a combatant.",
            "Pink means friend. Always.",
            "Won't hurt you or be destroyed.",
            "Guide these little stars home.",
        ),
    },
    {
        "name": "RAZOR WISP",
        "kind": "TRIANGLE CLASS",
        "sprite": "triangle",
        "lines": (
            "Fast, sharp, and deeply committed",
            "to making your day shorter.",
            "Loyal to their leaders, but not to you.",
        ),
    },
    {
        "name": "VIOLET WISP",
        "kind": "TRIANGLE CLASS",
        "sprite": "violet_triangle",
        "lines": (
            "Quicker and sharper than the average triangle.",
            "Yellow triangles fear them, and you should too.",
        ),
    },
    {
        "name": "IRON SENTINEL",
        "kind": "RECTANGLE CLASS",
        "sprite": "rectangle",
        "lines": (
            "A slow, armored marksman.",
            "Their plasma is small, but deadly.",
            "They are not fast, but they are patient.",
            "They are not smart, but they are persistent.",
        ),
    },
    {
        "name": "BLUE BASTION",
        "kind": "RECTANGLE CLASS",
        "sprite": "blue_rectangle",
        "lines": (
            "Always blue.",
            "Criminally accurate, and criminally armored.",
            "They don't take orders from anyone",
            "and they don't take prisoners. They are the law.",
        ),
    },
    {
        "name": "AEGIS VEST",
        "kind": "ARMOR PICKUP",
        "sprite": "armor",
        "lines": (
            "Found in dead ends. Naturally.",
            "Each vest absorbs five hits.",
            "You can wear two at once.",
            "Fashionable. Mildly bulletproof.",
        ),
    },
    {
        "name": "VITAL SPARK",
        "kind": "HEALTH PICKUP",
        "sprite": "health",
        "lines": (
            "A rare field ration.",
            "Restores all health on touch.",
            "The maze sometimes shows mercy.",
            "A welcome break from bad company.",
        ),
    },
    {
        "name": "BOOSTER",
        "kind": "VIOLET TRIANGLE DROP",
        "sprite": "quad",
        "lines": (
            "Full health, armor, and heavy fire.",
            "Your whole arsenal gets a refill.",
        ),
    },
    {
        "name": "QUAD DAMAGE",
        "kind": "SENTINEL POWER CORE // 15 SECONDS",
        "sprite": "quad_damage",
        "lines": (
            "A Sentinel's volatile power core.",
            "Fourfold glow. A beefy cannon roar.",
            "Use at your own risk. 15 seconds of glory.",
        ),
    },
    {
        "name": "SUPER SPEED",
        "kind": "VIOLET TRIANGLE DROP",
        "sprite": "super_speed",
        "lines": (
            "The core of a violet wisp.",
            "A crystal that inherits the speed of its former owner.",
        ),
    },
)


@lru_cache(maxsize=1)
def make_traitor_sphere_group_texture():
    """Build a small crowd of hostile spheres for the field-guide preview."""
    texture = pygame.Surface((144, 144), pygame.SRCALPHA)
    spheres = (
        (35, 55, 38, (80, 240, 135), 10),
        (82, 44, 42, (80, 170, 255), 28),
        (109, 77, 34, (255, 184, 72), 44),
        (51, 91, 42, (185, 115, 255), 56),
        (82, 93, 50, (80, 240, 135), 18),
    )
    for center_x, center_y, size, color, light_bucket in spheres:
        orb = pygame.transform.scale(
            make_enemy_texture(color, light_bucket, size=16), (size, size)
        )
        texture.blit(orb, (center_x - size // 2, center_y - size // 2))
    return texture


@lru_cache(maxsize=1)
def make_controls_card_texture():
    """Draw only chunky arcade keycaps for the controls card."""
    size = 144
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    dark = (8, 24, 18)
    green = (70, 255, 130)
    pale = (225, 255, 232)
    key_font = pygame.font.SysFont("monospace", 10, bold=True)

    def draw_key(label, rect):
        pygame.draw.rect(texture, dark, rect, border_radius=4)
        pygame.draw.rect(texture, green, rect, 2, border_radius=4)
        text = key_font.render(label, True, pale)
        texture.blit(text, (rect[0] + (rect[2] - text.get_width()) // 2,
                            rect[1] + (rect[3] - text.get_height()) // 2))

    draw_key("W", (60, 12, 24, 22))
    draw_key("A", (32, 38, 24, 22))
    draw_key("S", (60, 38, 24, 22))
    draw_key("D", (88, 38, 24, 22))
    draw_key("J", (22, 70, 24, 22))
    draw_key("K", (52, 70, 24, 22))
    draw_key("SHIFT", (82, 70, 48, 22))
    draw_key("F", (16, 106, 24, 22))
    draw_key("ESC", (46, 106, 38, 22))
    draw_key("SPACE", (90, 106, 42, 22))
    return texture


def draw_attract_screen(target, elapsed_ms):
    """Draw the idle arcade field guide with each sample's movement style."""
    target.fill((3, 8, 6))
    section_index = int(elapsed_ms // ATTRACT_SECTION_MS)
    card_index = section_index % len(ATTRACT_CARDS)
    card = ATTRACT_CARDS[card_index]
    green = (65, 255, 130)
    white = (245, 248, 245)
    title_font = pygame.font.SysFont("monospace", max(20, HEIGHT // 20), bold=True)
    name_font = pygame.font.SysFont("monospace", max(18, HEIGHT // 25), bold=True)
    body_font = pygame.font.SysFont("monospace", max(12, HEIGHT // 36), bold=True)
    small_font = pygame.font.SysFont("monospace", max(10, HEIGHT // 48), bold=True)

    title = title_font.render("FIELD GUIDE", True, white)
    target.blit(title, (int(WIDTH * 0.06), int(HEIGHT * 0.07)))
    subtitle = small_font.render("SHAP3D // SURVIVAL DATABASE", True, green)
    target.blit(subtitle, (int(WIDTH * 0.06), int(HEIGHT * 0.07) + title.get_height() + 5))

    panel = pygame.Rect(int(WIDTH * 0.06), int(HEIGHT * 0.27),
                        int(WIDTH * 0.38), int(HEIGHT * 0.51))
    pygame.draw.rect(target, (0, 0, 0), panel)
    pygame.draw.rect(target, green, panel, max(2, WIDTH // 240))
    pygame.draw.rect(target, (24, 90, 48), panel.inflate(-10, -10), 1)
    panel_label = small_font.render(card["kind"], True, green)
    target.blit(panel_label, (panel.centerx - panel_label.get_width() // 2,
                              panel.y + 12))

    if card["sprite"] == "controls":
        texture = make_controls_card_texture()
        sprite_size = 144
    elif card["sprite"] == "sphere":
        texture = make_traitor_sphere_group_texture()
        sprite_size = 144
    elif card["sprite"] == "friendly_sphere":
        texture = make_enemy_texture((255, 100, 190), 10)
        sprite_size = 144
    elif card["sprite"] in ("triangle", "violet_triangle"):
        triangle_color = (TRIANGLE_VIOLET if card["sprite"] == "violet_triangle"
                          else TRIANGLE_YELLOW)
        texture = make_triangle_texture(triangle_color)
        sprite_size = 144
    elif card["sprite"] in ("rectangle", "blue_rectangle"):
        blue_variant = card["sprite"] == "blue_rectangle"
        sprite_size = 144
        if blue_variant:
            texture = pygame.transform.scale(
                make_blue_sentinel_texture(), (sprite_size, sprite_size)
            )
        else:
            texture = pygame.transform.scale(
                make_rectangle_texture(RECTANGLE_RED), (sprite_size, sprite_size)
            )
    elif card["sprite"] == "health":
        texture = HEALTH_TEXTURE
        sprite_size = 144
    elif card["sprite"] == "quad":
        texture = QUAD_TEXTURE
        sprite_size = 144
    elif card["sprite"] == "quad_damage":
        texture = QUAD_DAMAGE_TEXTURE
        sprite_size = 144
    elif card["sprite"] == "super_speed":
        texture = SUPER_SPEED_TEXTURE
        sprite_size = 144
    else:
        texture = ARMOR_TEXTURE
        sprite_size = 144

    if texture.get_size() != (sprite_size, sprite_size):
        texture = pygame.transform.scale(texture, (sprite_size, sprite_size))
    animation_phase = pygame.time.get_ticks() / 520.0
    sprite_kind = card["sprite"]
    bob = (math.sin(animation_phase) * 7.0
           if sprite_kind in ("controls", "sphere",
                              "friendly_sphere", "armor",
                              "health", "quad",
                              "quad_damage", "super_speed") else 0.0)
    if sprite_kind in ("triangle", "violet_triangle"):
        sway = math.sin(animation_phase) * 7.0
    elif sprite_kind in ("rectangle", "blue_rectangle"):
        sway = math.sin(animation_phase) * 5.0
    else:
        sway = 0.0
    sprite_x = int(panel.centerx - sprite_size // 2 + sway)
    base_sprite_y = int(panel.y + 44 + (panel.height - 44 - sprite_size) / 2)
    sprite_y = int(base_sprite_y + bob)
    reflection_scale = 1.0 - bob * 0.004
    reflection_width = int((sprite_size + 30) * reflection_scale)
    reflection_height = max(18, int((sprite_size // 3) * reflection_scale))
    halo = pygame.Surface((reflection_width, reflection_height), pygame.SRCALPHA)
    halo_alpha = 35 + int(18 * (0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 700.0)))
    halo_color = ((255, 100, 190) if sprite_kind == "friendly_sphere"
                  else (205, 90, 255) if sprite_kind == "quad"
                  else QUAD_DAMAGE_ITEM_COLOR if sprite_kind == "quad_damage"
                  else (65, 205, 255) if sprite_kind == "super_speed"
                  else (50, 255, 115))
    pygame.draw.ellipse(
        halo, (*halo_color, halo_alpha), halo.get_rect().inflate(-8, -8)
    )
    reflection_center_x = panel.centerx
    if sprite_kind in ("rectangle", "blue_rectangle"):
        rectangle_feet_y = sprite_y + int(sprite_size * 20 / 24)
        reflection_center_y = rectangle_feet_y
    else:
        reflection_center_y = base_sprite_y + sprite_size + 5
    target.blit(halo, (int(reflection_center_x - halo.get_width() // 2),
                       int(reflection_center_y - halo.get_height() // 2)))
    target.blit(texture, (sprite_x, sprite_y))

    text_x = int(WIDTH * 0.51)
    text_y = int(HEIGHT * 0.32)
    name = name_font.render(card["name"], True, white)
    target.blit(name, (text_x, text_y))
    rule_y = text_y + name.get_height() + 8
    pygame.draw.line(target, green, (text_x, rule_y),
                     (int(WIDTH * 0.94), rule_y), max(1, WIDTH // 640))
    line_height = body_font.get_linesize() + 5
    max_text_width = int(WIDTH * 0.94) - text_x
    wrapped_lines = []
    for line in card["lines"]:
        words = line.split()
        wrapped = ""
        for word in words:
            candidate = word if not wrapped else f"{wrapped} {word}"
            if wrapped and body_font.size(candidate)[0] > max_text_width:
                wrapped_lines.append(wrapped)
                wrapped = word
            else:
                wrapped = candidate
        if wrapped:
            wrapped_lines.append(wrapped)
    for line_index, line in enumerate(wrapped_lines):
        rendered = body_font.render(line, True, white)
        target.blit(rendered, (text_x, rule_y + 20 + line_index * line_height))

    counter = small_font.render(
        f"{card_index + 1:02d} / {len(ATTRACT_CARDS):02d}", True, green
    )
    target.blit(counter, (text_x, int(HEIGHT * 0.72)))
    prompt = small_font.render("SPACE: BACK TO TITLE", True, white)
    target.blit(prompt, (int(WIDTH * 0.06), int(HEIGHT * 0.89)))

    # Carry the game's colored film grain into the field guide screen.
    screen_grain.fill((0, 0, 0, 0))
    noise_colors = ((220, 205, 255), (170, 115, 255),
                    (255, 255, 255), (130, 70, 220))
    for _ in range(5000):
        x = random.randrange(WIDTH)
        y = random.randrange(HEIGHT)
        color = random.choice(noise_colors)
        alpha = random.randint(20, 60)
        pygame.draw.line(screen_grain, (*color, alpha), (x, y), (x, y))
    target.blit(screen_grain, (0, 0))


def find_title_hall():
    """Pick the nearest seeded 4x4 hall for the title-screen flyby."""
    start_x, start_y = spawn_cell_x, spawn_cell_y
    candidates = []
    start_chunk_x = start_x // CHUNK_SIZE
    start_chunk_y = start_y // CHUNK_SIZE
    for chunk_y in range(max(0, start_chunk_y - 2),
                         min(WORLD_CHUNKS_PER_SIDE, start_chunk_y + 3)):
        for chunk_x in range(max(0, start_chunk_x - 2),
                             min(WORLD_CHUNKS_PER_SIDE, start_chunk_x + 3)):
            for node_y in range(MAZE_NODES_PER_SIDE):
                for node_x in range(MAZE_NODES_PER_SIDE):
                    hall_id = (chunk_x * MAZE_NODES_PER_SIDE + node_x,
                               chunk_y * MAZE_NODES_PER_SIDE + node_y)
                    if not world_node_has_hall(*hall_id):
                        continue
                    cells = hall_cells(hall_id)
                    if not cells:
                        continue
                    center_x = chunk_x * CHUNK_SIZE + 3 + node_x * MAZE_NODE_SPACING
                    center_y = chunk_y * CHUNK_SIZE + 3 + node_y * MAZE_NODE_SPACING
                    distance_sq = (center_x - start_x) ** 2 + (center_y - start_y) ** 2
                    candidates.append((distance_sq, hall_id, cells, center_x, center_y))
    if not candidates:
        return None
    _, hall_id, cells, center_x, center_y = min(candidates, key=lambda item: item[0])
    return hall_id, cells, center_x, center_y


def make_pixelated_menu(labels):
    font = pygame.font.SysFont("monospace", max(15, HEIGHT // 26), bold=True)
    menu = {}
    for label in labels:
        text = font.render(label, False, (245, 245, 245))
        # Keep twice as many source pixels as before, then enlarge them for
        # the same display size so the pixel lettering reads more clearly.
        reduced = pygame.transform.scale(text, (text.get_width(), text.get_height()))
        menu[label] = pygame.transform.scale(reduced,
                                             (text.get_width() * 2, text.get_height() * 2))
    return menu


def draw_pixelated_menu(target, labels, menu, selection):
    centers = (int(WIDTH * 0.34), int(WIDTH * 0.68))
    menu_y = int(HEIGHT * 0.66)
    for index, label in enumerate(labels):
        text = menu[label]
        x = centers[index] - text.get_width() // 2
        target.blit(text, (x, menu_y))
        if index == selection and (pygame.time.get_ticks() // 250) % 2 == 0:
            mid_y = menu_y + text.get_height() // 2
            marker_x = x - 24
            for row, width in enumerate((3, 6, 9, 6, 3)):
                pygame.draw.rect(
                    target, (255, 42, 28),
                    (marker_x, mid_y - 9 + row * 4, width, 3),
                )


def make_pause_title():
    font = pygame.font.SysFont("monospace", max(18, HEIGHT // 16), bold=True)
    text = font.render("Pause", False, (245, 245, 245))
    reduced = pygame.transform.scale(text, (max(1, text.get_width() // 2),
                                            max(1, text.get_height() // 2)))
    pixelated = pygame.transform.scale(reduced,
                                       (text.get_width() * 2, text.get_height() * 2))
    shadow = font.render("Pause", False, (65, 65, 75))
    shadow = pygame.transform.scale(
        pygame.transform.scale(shadow, (max(1, shadow.get_width() // 2),
                                        max(1, shadow.get_height() // 2))),
        (shadow.get_width() * 2, shadow.get_height() * 2),
    )
    title = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    x = (WIDTH - pixelated.get_width()) // 2
    y = (HEIGHT - pixelated.get_height()) // 2
    title.blit(shadow, (x + 5, y + 7))
    title.blit(pixelated, (x, y))
    return title


game_over_title = make_game_over_title()
game_over_menu = make_pixelated_menu(("try again", "exit"))
pause_title = make_pause_title()
pause_menu = make_pixelated_menu(("resume", "exit"))
game_over_menu_visible = False
game_over_selection = 0
paused = False
pause_scene = None
pause_selection = 0
debug_noclip = False
debug_invulnerable = False
weapon_points = 0
player_weapon_level = 0
player_damage = 0
player_hit_cooldown = 0.0
player_regen_timer = 0.0
player_hit_flash = 0.0
game_over = False
game_over_scene = None
game_over_space_ready = 0
triangle_spawn_flash = 0.0
sphere_spawn_flash = 0.0
rectangle_spawn_flash = 0.0
last_triangle_spawn_cell = None
last_sentinel_spawn_cell = None
title_screen = True
title_map_visible = False
title_map_keys = set()
title_map_surface = None
title_map_center = [(spawn_cell_x + 0.5) * 2, (spawn_cell_y + 0.5) * 2]
TITLE_MAP_ZOOM = 4
attract_mode = False
title_idle_started = pygame.time.get_ticks()
attract_started = title_idle_started
start_world_position = (player_x, player_y, player_angle)
title_world_position = start_world_position
title_hall_id = None
start_title = make_start_title()
start_prompt = make_start_prompt()
title_rng = random.Random(WORLD_SEED ^ 0x534841503344)
title_hall = find_title_hall()
if title_hall is not None:
    title_hall_id, title_hall_cells, title_center_cell_x, title_center_cell_y = title_hall
    player_hall_id = title_hall_id
    player_x = (title_center_cell_x + 0.5) * TILE_SIZE
    player_y = (title_center_cell_y + 0.5) * TILE_SIZE
    for dir_x, dir_y in ((1, 0), (0, 1), (-1, 0), (0, -1)):
        if world_block(title_center_cell_x + dir_x * 3,
                       title_center_cell_y + dir_y * 3) == 0:
            player_angle = math.atan2(dir_y, dir_x)
            break
    title_world_position = (player_x, player_y, player_angle)

    demo_cells = [
        cell for cell in title_hall_cells
        if math.hypot(cell[0] - title_center_cell_x,
                      cell[1] - title_center_cell_y) * TILE_SIZE >= ENEMY_SPAWN_MIN_DISTANCE
    ]
    if len(demo_cells) < 3:
        demo_cells = [cell for cell in title_hall_cells
                      if cell != (title_center_cell_x, title_center_cell_y)]
    for index, (cell_x, cell_y) in enumerate(
            title_rng.sample(demo_cells, min(4, len(demo_cells)))):
        enemy_type = title_rng.choices(
            ("sphere", "triangle", "rectangle"), weights=(0.62, 0.23, 0.15)
        )[0]
        violet_variant = enemy_type == "triangle" and title_rng.random() < 0.20
        color = (hostile_sphere_color(title_rng) if enemy_type == "sphere" else
                 TRIANGLE_VIOLET if violet_variant else TRIANGLE_YELLOW)
        enemy = make_enemy_record(
            cell_x, cell_y, enemy_type, color, violet_variant=violet_variant
        )
        enemy["spawn_fx"] = 0.0
        enemy["wander_cells"] = set(title_hall_cells)
        enemy["wander_target"] = None
        enemy["wander_speed"] = title_rng.uniform(28.0, 68.0)
        enemy["wander_seed"] = world_hash(cell_x + index * 101, cell_y - index * 73)
        enemy["wander_rng"] = random.Random(enemy["wander_seed"])
        enemies.append(enemy)
title_demo_templates = [enemy.copy() for enemy in enemies]
title_idle_started = pygame.time.get_ticks()
attract_started = title_idle_started


def return_to_title_screen():
    global title_screen, player_x, player_y, player_angle, player_hall_id
    global player_damage, player_hit_cooldown, player_regen_timer, player_hit_flash
    global triangle_spawn_flash, sphere_spawn_flash, rectangle_spawn_flash
    global last_triangle_spawn_cell, last_sentinel_spawn_cell
    global game_over, game_over_scene
    global game_over_menu_visible, game_over_selection, paused, pause_scene
    global armor_hits_remaining
    global weapon_points, player_weapon_level
    global boss_room_active, boss_spheres, boss_wave_stage
    global boss_triangle_spawn_timer
    global boss_battle_complete, boss_cage_destroyed, boss_cage_destroy_timer
    global boss_cage_blasts
    global player_in_open_space, victory_screen_active
    global attract_mode, title_idle_started, attract_started
    global title_music_started
    title_screen = True
    attract_mode = False
    title_idle_started = pygame.time.get_ticks()
    attract_started = title_idle_started
    player_x, player_y, player_angle = title_world_position
    boss_room_active = False
    boss_battle_complete = False
    boss_cage_destroyed = False
    boss_cage_destroy_timer = 0.0
    boss_cage_blasts.clear()
    player_in_open_space = False
    victory_screen_active = False
    boss_wave_stage = 0
    boss_triangle_spawn_timer = 0.0
    boss_spheres.clear()
    projectiles.clear()
    player_markers.clear()
    hostile_projectiles.clear()
    enemies.clear()
    armor_pickups.clear()
    health_pickups.clear()
    quad_pickups.clear()
    quad_damage_pickups.clear()
    super_speed_pickups.clear()
    opened_shortcuts.clear()
    shortcut_blast_timers.clear()
    loaded_armor_chunks.clear()
    armor_hits_remaining = 0
    super_speed_timer = 0.0
    quad_damage_timer = 0.0
    weapon_points = 0
    player_weapon_level = 0
    for template in title_demo_templates:
        enemy = template.copy()
        enemy["wander_target"] = None
        enemy["wander_rng"] = random.Random(enemy["wander_seed"])
        enemies.append(enemy)
    player_hall_id = title_hall_id
    player_damage = 0
    player_hit_cooldown = 0.0
    player_regen_timer = 0.0
    player_hit_flash = 0.0
    triangle_spawn_flash = 0.0
    sphere_spawn_flash = 0.0
    rectangle_spawn_flash = 0.0
    last_triangle_spawn_cell = None
    last_sentinel_spawn_cell = None
    game_over = False
    game_over_scene = None
    game_over_menu_visible = False
    game_over_selection = 0
    paused = False
    pause_scene = None
    if pygame.mixer.get_init():
        pygame.mixer.Channel(0).stop()
        pygame.mixer.Channel(0).play(generated_music, loops=-1)
        title_music_started = pygame.time.get_ticks()

running = True
while running:
    now = pygame.time.get_ticks()
    if (title_screen and not title_map_visible and not attract_mode
            and now - title_idle_started >= 10000):
        attract_mode = True
        attract_started = now
        if pygame.mixer.get_init() and attract_music is not None:
            pygame.mixer.Channel(0).stop()
            pygame.mixer.Channel(0).play(attract_music, loops=-1)

    for event in pygame.event.get():
        if event.type == pygame.KEYUP:
            title_map_keys.discard(event.key)
        elif event.type == pygame.QUIT:
            running = False
        elif victory_screen_active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                return_to_title_screen()
        elif title_screen and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif title_map_visible:
                if event.key == pygame.K_SPACE:
                    title_map_visible = False
                    title_map_keys.clear()
                    attract_mode = False
                    title_idle_started = pygame.time.get_ticks()
                    if pygame.mixer.get_init() and generated_music is not None:
                        pygame.mixer.Channel(0).stop()
                        pygame.mixer.Channel(0).play(generated_music, loops=-1)
                        title_music_started = pygame.time.get_ticks()
            elif event.key in (pygame.K_m, pygame.K_a, pygame.K_p):
                title_map_keys.add(event.key)
                if all(key in title_map_keys for key in
                       (pygame.K_m, pygame.K_a, pygame.K_p)):
                    title_map_visible = True
                    attract_mode = False
                    title_map_surface = print_map_png()
                    title_idle_started = pygame.time.get_ticks()
                    if pygame.mixer.get_init() and generated_music is not None:
                        pygame.mixer.Channel(0).stop()
                        pygame.mixer.Channel(0).play(generated_music, loops=-1)
                        title_music_started = pygame.time.get_ticks()
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                if attract_mode:
                    attract_mode = False
                    title_idle_started = pygame.time.get_ticks()
                    if pygame.mixer.get_init() and generated_music is not None:
                        pygame.mixer.Channel(0).stop()
                        pygame.mixer.Channel(0).play(generated_music, loops=-1)
                        title_music_started = pygame.time.get_ticks()
                else:
                    title_screen = False
                    print(f"Run seed: {WORLD_SEED} (replay with --seed {WORLD_SEED})",
                          flush=True)
                    play_sfx("start")
                    player_x, player_y, player_angle = start_world_position
                    boss_room_active = False
                    boss_battle_complete = False
                    boss_cage_destroyed = False
                    boss_cage_destroy_timer = 0.0
                    boss_cage_blasts.clear()
                    player_in_open_space = False
                    victory_screen_active = False
                    boss_wave_stage = 0
                    boss_triangle_spawn_timer = 0.0
                    boss_spheres.clear()
                    projectiles.clear()
                    player_markers.clear()
                    hostile_projectiles.clear()
                    enemies.clear()
                    armor_pickups.clear()
                    health_pickups.clear()
                    quad_pickups.clear()
                    quad_damage_pickups.clear()
                    super_speed_pickups.clear()
                    opened_shortcuts.clear()
                    shortcut_blast_timers.clear()
                    loaded_armor_chunks.clear()
                    armor_hits_remaining = 0
                    super_speed_timer = 0.0
                    quad_damage_timer = 0.0
                    weapon_points = 0
                    player_weapon_level = 0
                    player_hall_id = None
                    player_damage = 0
                    player_hit_cooldown = 0.0
                    player_regen_timer = 0.0
                    player_hit_flash = 0.0
                    triangle_spawn_flash = 0.0
                    sphere_spawn_flash = 0.0
                    rectangle_spawn_flash = 0.0
                    last_triangle_spawn_cell = None
                    last_sentinel_spawn_cell = None
        elif game_over and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE and pygame.time.get_ticks() >= game_over_space_ready:
                if not game_over_menu_visible:
                    game_over_menu_visible = True
                elif game_over_selection == 1:
                    play_sfx("menu_select")
                    running = False
                else:
                    play_sfx("menu_select")
                    return_to_title_screen()
            elif game_over_menu_visible and event.key == pygame.K_a:
                if game_over_selection != 0:
                    game_over_selection = 0
                    play_sfx("menu_move")
            elif game_over_menu_visible and event.key == pygame.K_d:
                if game_over_selection != 1:
                    game_over_selection = 1
                    play_sfx("menu_move")
            elif game_over_menu_visible and event.key == pygame.K_RETURN:
                play_sfx("menu_select")
                if game_over_selection == 1:
                    running = False
                else:
                    return_to_title_screen()
        elif not game_over and paused and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                paused = False
                pause_scene = None
                if pygame.mixer.get_init():
                    pygame.mixer.Channel(0).unpause()
            elif event.key == pygame.K_a:
                if pause_selection != 0:
                    pause_selection = 0
                    play_sfx("menu_move")
            elif event.key == pygame.K_d:
                if pause_selection != 1:
                    pause_selection = 1
                    play_sfx("menu_move")
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                play_sfx("menu_select")
                if pause_selection == 1:
                    running = False
                else:
                    paused = False
                    pause_scene = None
                    if pygame.mixer.get_init():
                        pygame.mixer.Channel(0).unpause()
        elif not game_over and event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            paused = True
            pause_scene = screen.copy()
            pause_selection = 0
            if pygame.mixer.get_init():
                pygame.mixer.Channel(0).pause()
        elif (not title_screen and not game_over and not paused and args.debug
              and event.type == pygame.KEYDOWN
              and event.key in (pygame.K_u, pygame.K_i, pygame.K_m, pygame.K_v,
                                pygame.K_q, pygame.K_0,
                                pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                                pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8,
                                pygame.K_9)):
            if event.key == pygame.K_u:
                debug_noclip = not debug_noclip
            elif event.key == pygame.K_i:
                debug_invulnerable = not debug_invulnerable
            elif event.key == pygame.K_0:
                jump_to_nearest_hidden_shortcut()
            elif event.key == pygame.K_1:
                spawn_debug_armor()
            elif event.key == pygame.K_2:
                spawn_debug_health()
            elif event.key == pygame.K_3:
                spawn_debug_quad()
            elif event.key == pygame.K_4:
                spawn_debug_super_speed()
            elif event.key == pygame.K_q:
                spawn_debug_quad_damage()
            elif event.key == pygame.K_5:
                spawn_debug_enemy("sphere")
            elif event.key == pygame.K_6:
                spawn_debug_enemy("triangle")
            elif event.key == pygame.K_7:
                spawn_debug_enemy("rectangle")
            elif event.key == pygame.K_8:
                spawn_debug_enemy("rectangle", blue_cannon=True)
            elif event.key == pygame.K_9:
                spawn_debug_friendly_sphere()
            elif event.key == pygame.K_m:
                player_x = (BOSS_ROOM_LEFT + 2.5) * TILE_SIZE
                player_y = (BOSS_ROOM_TOP + 2.5) * TILE_SIZE
                player_angle = math.atan2(
                    (BOSS_CORE_TOP + 1.0) * TILE_SIZE - player_y,
                    (BOSS_CORE_LEFT + 1.0) * TILE_SIZE - player_x,
                )
                player_hall_id = None
                start_boss_room()
            elif event.key == pygame.K_v:
                boss_room_active = False
                boss_battle_complete = False
                boss_cage_destroyed = False
                boss_cage_destroy_timer = 0.0
                boss_cage_blasts.clear()
                boss_wave_stage = 0
                player_in_open_space = False
                victory_screen_active = False
                enemies.clear()
                hostile_projectiles.clear()
                projectiles.clear()
                boss_spheres.clear()
                player_x = (BOSS_CORE_LEFT - 0.5) * TILE_SIZE
                player_y = (BOSS_CORE_TOP + 0.5) * TILE_SIZE
                player_angle = 0.0
                player_hall_id = None
                start_boss_room()
                finish_boss_battle()
        elif (not title_screen and not game_over and not paused
              and event.type == pygame.KEYDOWN
              and event.key in (pygame.K_SPACE, pygame.K_f)):
            marker_shot = event.key == pygame.K_f
            fire_player_shot(marker_shot)
            if event.key == pygame.K_SPACE and super_speed_timer > 0.0:
                player_fire_timer = SUPER_SPEED_FIRE_INTERVAL

    if not running:
        break
    if victory_screen_active:
        draw_victory_screen(screen)
        pygame.display.flip()
        clock.tick(30)
        continue
    if paused:
        if pause_scene is not None:
            screen.blit(pause_scene, (0, 0))
        screen.blit(pause_title, (0, 0))
        draw_pixelated_menu(screen, ("resume", "exit"), pause_menu, pause_selection)
        pygame.display.flip()
        clock.tick(60)
        continue
    if game_over:
        if game_over_scene is not None:
            screen.blit(game_over_scene, (0, 0))
        screen.blit(game_over_title, (0, 0))
        if game_over_menu_visible:
            draw_pixelated_menu(screen, ("try again", "exit"),
                                game_over_menu, game_over_selection)
        pygame.display.flip()
        clock.tick(60)
        continue
            
    # wasd movement with collision detection and wall sliding
    keys = pygame.key.get_pressed()
    if title_screen and title_map_visible and title_map_surface is not None:
        pan_distance = 72.0 * clock.get_time() / 1000.0
        if keys[pygame.K_w]:
            title_map_center[1] -= pan_distance
        if keys[pygame.K_s]:
            title_map_center[1] += pan_distance
        if keys[pygame.K_a]:
            title_map_center[0] -= pan_distance
        if keys[pygame.K_d]:
            title_map_center[0] += pan_distance
        crop_width = max(1, title_map_surface.get_width() // TITLE_MAP_ZOOM)
        crop_height = max(1, title_map_surface.get_height() // TITLE_MAP_ZOOM)
        title_map_center[0] = max(crop_width / 2, min(
            title_map_surface.get_width() - crop_width / 2, title_map_center[0]
        ))
        title_map_center[1] = max(crop_height / 2, min(
            title_map_surface.get_height() - crop_height / 2, title_map_center[1]
        ))
    base_move_speed = 3.6 if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else 2.0
    move_speed = (base_move_speed * (1.0 + 0.08 * player_weapon_level)
                  * (1.5 if super_speed_timer > 0.0 else 1.0))
    move = 0
    if not title_screen and keys[pygame.K_w]:
        move += move_speed
    if not title_screen and keys[pygame.K_s]:
        move -= move_speed

    def is_open(x, y):
        cell_x = math.floor(x / TILE_SIZE)
        cell_y = math.floor(y / TILE_SIZE)
        return world_block(cell_x, cell_y) == 0

    def try_player_step(next_x, next_y, step_x, step_y):
        global player_x, player_y
        old_cell = (math.floor(player_x / TILE_SIZE),
                    math.floor(player_y / TILE_SIZE))
        next_cell = (math.floor(next_x / TILE_SIZE), math.floor(next_y / TILE_SIZE))
        pair = hidden_shortcut_lookup().get(next_cell)
        if (pair is not None and next_cell in opened_shortcuts
                and old_cell == (next_cell[0] - pair[4], next_cell[1] - pair[5])
                and step_x * pair[4] + step_y * pair[5] > 0.0):
            entry_x, entry_y, exit_x, exit_y, face_x, face_y = pair
            player_x = next_x + (exit_x - entry_x + face_x) * TILE_SIZE
            player_y = next_y + (exit_y - entry_y + face_y) * TILE_SIZE
            return True
        if debug_noclip or is_open(next_x, next_y):
            player_x, player_y = next_x, next_y
            return True
        return False

    if move:
        dx = math.cos(player_angle) * move
        dy = math.sin(player_angle) * move

        # Resolve the axes separately. This preserves the unobstructed
        # component when one axis hits a wall, allowing the player to glide.
        # If both axes are blocked, neither component is applied.
        try_player_step(player_x + dx, player_y, dx, 0.0)
        try_player_step(player_x, player_y + dy, 0.0, dy)

    strafe = 0
    if not title_screen and keys[pygame.K_a]:
        strafe -= move_speed
    if not title_screen and keys[pygame.K_d]:
        strafe += move_speed
    if strafe:
        strafe_angle = player_angle + math.pi / 2
        strafe_x = math.cos(strafe_angle) * strafe
        strafe_y = math.sin(strafe_angle) * strafe
        try_player_step(player_x + strafe_x, player_y, strafe_x, 0.0)
        try_player_step(player_x, player_y + strafe_y, 0.0, strafe_y)

    player_cell = (math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE))
    if (boss_battle_complete and not player_in_open_space
            and player_cell == BOSS_ESCAPE_PORTAL_CELL):
        player_in_open_space = True
    if (not title_screen and not boss_room_active
            and BOSS_ROOM_LEFT < player_cell[0] < BOSS_ROOM_RIGHT
            and BOSS_ROOM_TOP < player_cell[1] < BOSS_ROOM_BOTTOM
            and world_cell_type(*player_cell) == 0):
        start_boss_room()

    if not title_screen and keys[pygame.K_j]:
        player_angle -= 0.05
    if not title_screen and keys[pygame.K_k]:
        player_angle += 0.05

    # Generate a deterministic neighborhood around the player's current cell.
    visible_map = generate_visible_map(player_x, player_y, VIEW_DISTANCE_BLOCKS)
    if not title_screen:
        visible_chunks = {
            (math.floor(cell_x / CHUNK_SIZE), math.floor(cell_y / CHUNK_SIZE))
            for cell_x, cell_y in visible_map
        }
        for chunk_x, chunk_y in visible_chunks:
            chunk_key = (chunk_x, chunk_y)
            if chunk_key in loaded_armor_chunks:
                continue
            loaded_armor_chunks.add(chunk_key)
            for cell_x, cell_y in armor_pickups_in_chunk(chunk_x, chunk_y):
                armor_pickups.append({
                    "x": (cell_x + 0.5) * TILE_SIZE,
                    "y": (cell_y + 0.5) * TILE_SIZE,
                })
    current_hall_id = hall_at_cell(
        math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE)
    )
    if (not title_screen and current_hall_id is not None
            and current_hall_id != player_hall_id):
        spawn_hall_enemies(enemies, current_hall_id)
    player_hall_id = current_hall_id

    # Move projectiles through the map and start an explosion on wall impact.
    frame_time = clock.get_time() / 1000.0
    for shortcut_cell in list(shortcut_blast_timers):
        shortcut_blast_timers[shortcut_cell] -= frame_time
        if shortcut_blast_timers[shortcut_cell] <= 0.0:
            del shortcut_blast_timers[shortcut_cell]
    triangle_spawn_flash = max(0.0, triangle_spawn_flash - frame_time)
    super_speed_was_active = super_speed_timer > 0.0
    super_speed_timer = max(0.0, super_speed_timer - frame_time)
    quad_damage_timer = max(0.0, quad_damage_timer - frame_time)
    if super_speed_was_active and super_speed_timer == 0.0:
        play_weapon_music()
    player_fire_timer = max(0.0, player_fire_timer - frame_time)
    if (not title_screen and super_speed_timer > 0.0
            and keys[pygame.K_SPACE]):
        if player_fire_timer <= 0.0:
            fire_player_shot()
            player_fire_timer = SUPER_SPEED_FIRE_INTERVAL
    else:
        player_fire_timer = 0.0
    sphere_spawn_flash = max(0.0, sphere_spawn_flash - frame_time)
    rectangle_spawn_flash = max(0.0, rectangle_spawn_flash - frame_time)
    update_boss_victory_fx(frame_time)
    update_boss_spheres(frame_time)
    player_cell = (math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE))
    for pickup in armor_pickups[:]:
        if math.hypot(pickup["x"] - player_x, pickup["y"] - player_y) <= 22.0:
            armor_hits_remaining = min(
                MAX_ARMOR_HITS, armor_hits_remaining + ARMOR_HITS_PER_PICKUP
            )
            armor_pickups.remove(pickup)
            play_sfx("armor_pickup")

    if not title_screen and boss_room_active and not boss_battle_complete:
        boss_triangle_spawn_timer -= frame_time
        if boss_triangle_spawn_timer <= 0.0:
            if not any(enemy.get("type") == "triangle" for enemy in enemies):
                triangle_cell = triangle_spawn_cell_toward_center(
                    player_cell, min_steps=4, max_steps=9
                )
                if triangle_cell is not None:
                    cell_x, cell_y = triangle_cell
                    spawn_center_triangle(cell_x, cell_y, 1.0)
            boss_triangle_spawn_timer = random.uniform(12.0, 20.0)
    elif (not title_screen and not boss_battle_complete
          and player_cell != last_triangle_spawn_cell):
        last_triangle_spawn_cell = player_cell
        distance_factor = center_difficulty_factor(
            player_cell[0] * TILE_SIZE, player_cell[1] * TILE_SIZE
        )
        triangle_chance = 0.02 + 0.18 * distance_factor
        if (not any(enemy.get("type") == "triangle" for enemy in enemies)
                and random.random() < triangle_chance):
            triangle_cell = triangle_spawn_cell_toward_center(player_cell)
            if triangle_cell is not None:
                cell_x, cell_y = triangle_cell
                spawn_center_triangle(
                    cell_x, cell_y,
                    enemy_hit_multiplier(cell_x * TILE_SIZE, cell_y * TILE_SIZE),
                )
    if (not title_screen and not boss_battle_complete
            and player_cell != last_sentinel_spawn_cell):
        last_sentinel_spawn_cell = player_cell
        distance_factor = center_difficulty_factor(
            player_cell[0] * TILE_SIZE, player_cell[1] * TILE_SIZE
        )
        sentinel_chance = 0.02 + 0.18 * distance_factor
        if (not any(enemy.get("random_center_sentinel") for enemy in enemies)
                and random.random() < sentinel_chance):
            spawn_center_sentinel(player_cell)
    if title_screen:
        update_title_demo_enemies(enemies, frame_time)
    else:
        update_enemies(enemies, player_x, player_y, frame_time)
    for enemy in (() if title_screen else enemies):
        enemy["spawn_fx"] = max(0.0, enemy.get("spawn_fx", 0.0) - frame_time)
    for enemy in enemies:
        if enemy.get("type") != "rectangle" or enemy["virtual"]:
            continue
        enemy_distance = math.hypot(enemy["x"] - player_x, enemy["y"] - player_y)
        if enemy_distance > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
            continue
        enemy["shot_timer"] -= frame_time
        if enemy["shot_timer"] <= 0.0:
            shot_angle = math.atan2(player_y - enemy["y"], player_x - enemy["x"])
            if enemy.get("boss"):
                plasma_type = ("green", "red", "blue")[enemy["plasma_cycle"] % 3]
                enemy["plasma_cycle"] += 1
                plasma_colors = {
                    "green": PLASMA_EXPLOSION_TINT,
                    "red": (255, 58, 38),
                    "blue": (70, 155, 255),
                }
                shot_damage = {"green": 1, "red": 2, "blue": 4}[plasma_type]
                shot_speed = 285.0
                shot_interval = 0.24
                shot_offset = ENEMY_RADIUS * 2.0 + 3.0
            else:
                plasma_type = "blue" if enemy.get("blue_cannon") else "red"
                plasma_colors = {
                    "red": (255, 58, 38), "blue": (70, 155, 255),
                }
                shot_damage = 4 if enemy.get("blue_cannon") else 2
                shot_speed = 190.0
                shot_interval = rectangle_shot_interval(enemy)
                shot_offset = ENEMY_RADIUS + 2.0
            hostile_projectiles.append({
                "x": enemy["x"] + math.cos(shot_angle) * shot_offset,
                "y": enemy["y"] + math.sin(shot_angle) * shot_offset,
                "angle": shot_angle,
                "age": 0.0,
                "explosion": 0.0,
                "blue_cannon": plasma_type == "blue",
                "plasma_type": plasma_type,
                "plasma_color": plasma_colors[plasma_type],
                "damage": shot_damage,
                "speed": shot_speed,
            })
            enemy["shot_timer"] = shot_interval
            play_sfx("blue_cannon_fire" if plasma_type == "blue" else "enemy_shoot")

    ranged_damage = 0
    for shot in hostile_projectiles[:]:
        shot["age"] += frame_time
        if shot["age"] >= 5.0:
            hostile_projectiles.remove(shot)
            continue
        if shot["explosion"] > 0.0:
            shot["explosion"] -= frame_time
            if shot["explosion"] <= 0.0:
                hostile_projectiles.remove(shot)
            continue
        travel = shot.get("speed", 190.0) * frame_time
        steps = max(1, math.ceil(travel / 3.0))
        step_distance = travel / steps
        for _ in range(steps):
            next_x = shot["x"] + math.cos(shot["angle"]) * step_distance
            next_y = shot["y"] + math.sin(shot["angle"]) * step_distance
            if not is_open(next_x, next_y):
                shot["explosion"] = PLASMA_EXPLOSION_DURATION
                play_sfx("blue_plasma_hit" if shot.get("blue_cannon")
                         else "enemy_plasma_explosion")
                break
            shot["x"], shot["y"] = next_x, next_y
            collision_radius = 22.0 if shot.get("blue_cannon") else 14.0
            if math.hypot(shot["x"] - player_x, shot["y"] - player_y) <= collision_radius:
                ranged_damage = max(
                    ranged_damage,
                    shot.get("damage", 4 if shot.get("blue_cannon") else 2),
                )
                shot["explosion"] = PLASMA_EXPLOSION_DURATION
                play_sfx("blue_plasma_hit" if shot.get("blue_cannon")
                         else "enemy_plasma_explosion")
                break

    for projectile in projectiles[:]:
        projectile["age"] += frame_time
        max_flight_time = 15.0 if projectile.get("marker_projectile") else 5.0
        if projectile["age"] >= max_flight_time:
            projectiles.remove(projectile)
            continue
        if projectile["explosion"] > 0:
            projectile["explosion"] -= frame_time
            if projectile["explosion"] <= 0:
                projectiles.remove(projectile)
            continue

        travel = 360.0 * frame_time
        steps = max(1, int(travel / 2.0))
        step_distance = travel / steps
        for _ in range(steps):
            curve = 0.075 * math.sin(projectile["age"] * 3.5 + projectile["curve_phase"])
            flight_angle = projectile["angle"] + curve
            next_x = projectile["x"] + math.cos(flight_angle) * step_distance
            next_y = projectile["y"] + math.sin(flight_angle) * step_distance
            impact_cell = (math.floor(next_x / TILE_SIZE),
                           math.floor(next_y / TILE_SIZE))
            shortcut_pair = hidden_shortcut_lookup().get(impact_cell)
            if (not projectile.get("marker_projectile")
                    and shortcut_pair is not None
                    and impact_cell not in opened_shortcuts
                    and (math.cos(flight_angle) * shortcut_pair[4]
                         + math.sin(flight_angle) * shortcut_pair[5]) > 0.35):
                projectile["x"], projectile["y"] = next_x, next_y
                projectile["depth"] = math.hypot(next_x - player_x, next_y - player_y)
                projectile["explosion"] = PLASMA_EXPLOSION_DURATION
                if quad_blast_hits_player_block(projectile):
                    ranged_damage = max(ranged_damage, 1)
                open_hidden_shortcut(impact_cell)
                break
            if not is_open(next_x, next_y):
                if projectile.get("marker_projectile"):
                    # Store the last open point so the wall's depth buffer does not
                    # hide the orb, while keeping its position fixed in world space.
                    marker_x = (projectile["x"] + next_x) * 0.5
                    marker_y = (projectile["y"] + next_y) * 0.5
                    player_markers.append({
                        "x": marker_x,
                        "y": marker_y,
                        "phase": random.random() * math.tau,
                        "marker": True,
                    })
                    if len(player_markers) > MAX_PLAYER_MARKERS:
                        del player_markers[0]
                    projectiles.remove(projectile)
                else:
                    # Keep the blast at the last open point, just in front of the wall.
                    projectile["explosion"] = PLASMA_EXPLOSION_DURATION
                    if quad_blast_hits_player_block(projectile):
                        ranged_damage = max(ranged_damage, 1)
                play_sfx("quad_damage_hit" if projectile.get("quad_damage")
                         else "wall")
                break

            # Test the projectile's world-space segment against active enemies.
            # Segment testing prevents fast shots from skipping over a sphere.
            old_x, old_y = projectile["x"], projectile["y"]
            dx, dy = next_x - old_x, next_y - old_y
            segment_length_sq = dx * dx + dy * dy
            struck_enemy = None
            impact_t = 1.0
            for enemy in (() if projectile.get("marker_projectile") else enemies):
                if enemy["virtual"] or enemy.get("friendly"):
                    continue
                hit_radius = ENEMY_RADIUS * (2.2 if enemy.get("boss") else 1.0) + 3.0
                ox, oy = old_x - enemy["x"], old_y - enemy["y"]
                b = 2.0 * (ox * dx + oy * dy)
                c = ox * ox + oy * oy - hit_radius * hit_radius
                if c <= 0:
                    t = 0.0
                else:
                    discriminant = b * b - 4.0 * segment_length_sq * c
                    if discriminant < 0 or segment_length_sq == 0:
                        continue
                    t = (-b - math.sqrt(discriminant)) / (2.0 * segment_length_sq)
                    if not 0.0 <= t <= 1.0:
                        continue
                if struck_enemy is None or t < impact_t:
                    struck_enemy, impact_t = enemy, t

            if struck_enemy is not None:
                projectile["x"] = old_x + dx * impact_t
                projectile["y"] = old_y + dy * impact_t
                projectile["depth"] = math.hypot(projectile["x"] - player_x, projectile["y"] - player_y)
                projectile["explosion"] = PLASMA_EXPLOSION_DURATION
                if quad_blast_hits_player_block(projectile):
                    ranged_damage = max(ranged_damage, 1)
                struck_enemy["hits"] = (
                    struck_enemy.get("hits", 0) + projectile.get("damage", 1)
                )
                if struck_enemy["hits"] >= enemy_hit_points(struck_enemy):
                    enemies.remove(struck_enemy)
                    if struck_enemy.get("boss"):
                        boss_wave_stage = 4
                    points_by_enemy = {"sphere": 1, "triangle": 2, "rectangle": 4}
                    points_earned = points_by_enemy.get(struck_enemy.get("type"), 1)
                    if (struck_enemy.get("type") == "rectangle"
                            and struck_enemy.get("blue_cannon")):
                        points_earned = 8
                    weapon_points = min(20, weapon_points + points_earned)
                    previous_weapon_level = player_weapon_level
                    player_weapon_level = min(2, weapon_points // 10)
                    # The larger burst marks the enemy's destruction.
                    projectile["enemy_kill"] = True
                    projectile["explosion_color"] = struck_enemy["color"]
                    health_drop_chance = 0.05 + 0.035 * player_damage
                    block_x = math.floor(struck_enemy["x"] / TILE_SIZE)
                    block_y = math.floor(struck_enemy["y"] / TILE_SIZE)
                    if random.random() < health_drop_chance:
                        health_pickups.append({
                            "block": (block_x, block_y),
                            "x": (block_x + 0.5) * TILE_SIZE,
                            "y": (block_y + 0.5) * TILE_SIZE,
                        })
                    if (struck_enemy.get("type") == "rectangle"
                            and not struck_enemy.get("boss")
                            and random.random() < 0.10):
                        quad_damage_pickups.append({
                            "block": (block_x, block_y),
                            "x": (block_x + 0.5) * TILE_SIZE,
                            "y": (block_y + 0.5) * TILE_SIZE,
                        })
                    if (struck_enemy.get("type") == "triangle"
                            and struck_enemy.get("violet_variant")):
                        violet_drop = random.random()
                        drop = {
                            "block": (block_x, block_y),
                            "x": (block_x + 0.5) * TILE_SIZE,
                            "y": (block_y + 0.5) * TILE_SIZE,
                        }
                        if violet_drop < 0.50:
                            super_speed_pickups.append(drop)
                        elif violet_drop < 0.75:
                            quad_pickups.append(drop)
                        else:
                            armor_pickups.append({
                                "x": drop["x"], "y": drop["y"],
                            })
                    play_sfx("enemy_death")
                    if player_weapon_level > previous_weapon_level:
                        play_sfx("weapon_level_up")
                        play_weapon_music()
                    if struck_enemy.get("boss"):
                        finish_boss_battle()
                else:
                    play_sfx("quad_damage_hit" if projectile.get("quad_damage")
                             else "enemy_hit")
                break

            projectile["x"] = next_x
            projectile["y"] = next_y
            projectile["depth"] += step_distance

    if boss_room_active:
        advance_boss_wave()

    for pickup in health_pickups[:]:
        distance = math.hypot(pickup["x"] - player_x, pickup["y"] - player_y)
        if distance > 50 * TILE_SIZE:
            health_pickups.remove(pickup)
        elif distance <= 22.0:
            player_damage = 0
            player_regen_timer = 0.0
            player_hit_flash = 0.0
            health_pickups.remove(pickup)
            play_sfx("health_pickup")

    for pickup in quad_pickups[:]:
        distance = math.hypot(pickup["x"] - player_x, pickup["y"] - player_y)
        if distance > 50 * TILE_SIZE:
            quad_pickups.remove(pickup)
        elif distance <= 22.0:
            player_damage = 0
            player_regen_timer = 0.0
            player_hit_flash = 0.0
            player_hit_cooldown = 0.0
            armor_hits_remaining = MAX_ARMOR_HITS
            weapon_points = 20
            player_weapon_level = 2
            quad_pickups.remove(pickup)
            play_sfx("booster_pickup")
            play_weapon_music()

    for pickup in quad_damage_pickups[:]:
        distance = math.hypot(pickup["x"] - player_x, pickup["y"] - player_y)
        if distance > 50 * TILE_SIZE:
            quad_damage_pickups.remove(pickup)
        elif distance <= 22.0:
            quad_damage_timer = 15.0
            quad_damage_pickups.remove(pickup)
            play_sfx("quad_damage_pickup")

    for pickup in super_speed_pickups[:]:
        distance = math.hypot(pickup["x"] - player_x, pickup["y"] - player_y)
        if distance > 50 * TILE_SIZE:
            super_speed_pickups.remove(pickup)
        elif distance <= 22.0:
            super_speed_timer = 15.0
            super_speed_pickups.remove(pickup)
            play_sfx("super_speed_pickup")
            play_weapon_music()

    # Enemy contact deals damage at most once every 0.25 seconds. A brief delay after
    # the last hit lets the player recover one hit every ten seconds.
    player_hit_cooldown = max(0.0, player_hit_cooldown - frame_time)
    player_hit_flash = max(0.0, player_hit_flash - frame_time)
    if player_damage:
        player_regen_timer += frame_time
        if player_regen_timer >= 10.0:
            player_damage = max(0, player_damage - 1)
            player_regen_timer -= 10.0
    else:
        player_regen_timer = 0.0

    if (not title_screen and not game_over and not debug_invulnerable
            and player_hit_cooldown <= 0.0):
        touching_enemy = ranged_damage > 0
        for enemy in enemies:
            if enemy["virtual"] or enemy.get("friendly"):
                continue
            dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
            distance = math.hypot(dx, dy)
            contact_distance = ENEMY_RADIUS * 2.2 if enemy.get("boss") else ENEMY_STOP_DISTANCE
            if distance > contact_distance:
                continue
            # Prevent damage through a wall while keeping the proximity check
            # inexpensive for the handful of nearby enemies.
            samples = max(1, math.ceil(distance / 8.0))
            if all(
                is_open(enemy["x"] - dx * step / samples,
                        enemy["y"] - dy * step / samples)
                for step in range(1, samples)
            ):
                touching_enemy = True
                break

        if touching_enemy:
            if armor_hits_remaining > 0:
                armor_hits_remaining -= 1
            else:
                if player_weapon_level > 0:
                    player_weapon_level = 0
                    play_weapon_music()
                weapon_points = 0
                player_damage += ranged_damage if ranged_damage else 1
            player_hit_cooldown = 0.25
            player_regen_timer = 0.0
            player_hit_flash = 0.38
            play_sfx("player_hit")
            if player_damage >= 10:
                game_over = True
                game_over_space_ready = pygame.time.get_ticks() + 5000
                if pygame.mixer.get_init() and game_over_music is not None:
                    pygame.mixer.Channel(0).stop()
                    pygame.mixer.Channel(0).play(game_over_music, loops=-1)

    screen.fill((3, 5, 18) if player_in_open_space else (10, 10, 10))

    # Raycasting Loop
    wall_depths = [float("inf")] * NUM_RAYS
    wall_tops = [HEIGHT // 2] * NUM_RAYS
    boss_glass_layer.fill((0, 0, 0, 0))
    max_ray_depth = VIEW_DISTANCE_BLOCKS * TILE_SIZE
    wall_light_sources = []
    for source in projectiles:
        source_tint = source.get(
            "explosion_color", source.get("weapon_color", PLASMA_EXPLOSION_TINT)
        )
        source_strength = 0.8
        if source.get("explosion", 0.0) > 0.0:
            source_strength *= 1.4 + 0.5 * (
                1.0 - source["explosion"] / PLASMA_EXPLOSION_DURATION
            )
        wall_light_sources.append((
            source, source_tint, source_strength, 180.0, False
        ))
    for source in hostile_projectiles:
        source_tint = source.get(
            "plasma_color", (70, 155, 255) if source.get("blue_cannon")
            else (255, 58, 38)
        )
        source_strength = 0.95
        if source.get("explosion", 0.0) > 0.0:
            source_strength *= 1.4 + 0.5 * (
                1.0 - source["explosion"] / PLASMA_EXPLOSION_DURATION
            )
        wall_light_sources.append((
            source, source_tint, source_strength, 180.0, False
        ))
    wall_light_sources.extend(
        (source, (255, 225, 35), 2.5, 224.0, True)
        for source in player_markers
    )
    for ray in range(NUM_RAYS):
        relative_angle = -HALF_FOV + ray * STEP_ANGLE
        ray_angle = player_angle + relative_angle
        sin_a = math.sin(ray_angle)
        cos_a = math.cos(ray_angle)
        shortcut_view_offset = None
        map_x = math.floor(player_x / TILE_SIZE)
        map_y = math.floor(player_y / TILE_SIZE)

        if cos_a > 0:
            step_x = 1
            next_x = (map_x + 1) * TILE_SIZE
            side_dist_x = (next_x - player_x) / cos_a
        elif cos_a < 0:
            step_x = -1
            next_x = map_x * TILE_SIZE
            side_dist_x = (next_x - player_x) / cos_a
        else:
            step_x = 0
            side_dist_x = float("inf")
        delta_dist_x = abs(TILE_SIZE / cos_a) if cos_a else float("inf")

        if sin_a > 0:
            step_y = 1
            next_y = (map_y + 1) * TILE_SIZE
            side_dist_y = (next_y - player_y) / sin_a
        elif sin_a < 0:
            step_y = -1
            next_y = map_y * TILE_SIZE
            side_dist_y = (next_y - player_y) / sin_a
        else:
            step_y = 0
            side_dist_y = float("inf")
        delta_dist_y = abs(TILE_SIZE / sin_a) if sin_a else float("inf")

        while True:
            # Jump directly to the next vertical or horizontal grid boundary.
            if side_dist_x < side_dist_y:
                depth = side_dist_x
                side_dist_x += delta_dist_x
                map_x += step_x
                hit_side = "x"
            else:
                depth = side_dist_y
                side_dist_y += delta_dist_y
                map_y += step_y
                hit_side = "y"

            if depth > max_ray_depth:
                break
            if shortcut_view_offset is None:
                if (map_x, map_y) not in visible_map:
                    break
                wall_type = visible_map[(map_x, map_y)]
            else:
                remote_x = map_x + shortcut_view_offset[0]
                remote_y = map_y + shortcut_view_offset[1]
                wall_type = world_cell_type(remote_x, remote_y)
                if wall_type in (6, 7):
                    wall_type = 1
            if wall_type == 0:
                continue

            hit_x = player_x + cos_a * depth
            hit_y = player_y + sin_a * depth
            mapped_hit_x = hit_x
            mapped_hit_y = hit_y
            if shortcut_view_offset is not None:
                mapped_hit_x += shortcut_view_offset[0] * TILE_SIZE
                mapped_hit_y += shortcut_view_offset[1] * TILE_SIZE
            corrected_depth = depth * math.cos(ray_angle - player_angle)
            if wall_type == 7 and shortcut_view_offset is None:
                shortcut_pair = hidden_shortcut_lookup().get((map_x, map_y))
                if hit_side == "x":
                    previous_cell = (map_x - step_x, map_y)
                else:
                    previous_cell = (map_x, map_y - step_y)
                if (shortcut_pair is not None
                        and previous_cell != (
                            map_x - shortcut_pair[4], map_y - shortcut_pair[5]
                        )):
                    wall_type = 6
                elif shortcut_pair is not None:
                    shortcut_view_offset = (
                        shortcut_pair[2] - map_x,
                        shortcut_pair[3] - map_y,
                    )
                    blast_remaining = shortcut_blast_timers.get((map_x, map_y), 0.0)
                    if blast_remaining > 0.0:
                        portal_height = min(
                            HEIGHT, int((TILE_SIZE / max(1.0, corrected_depth)) * DIST_PLANE)
                        )
                        portal_top = int(HEIGHT / 2 - portal_height / 2)
                        portal_bottom = int(HEIGHT / 2 + portal_height / 2)
                        flash = int(220 * min(1.0, blast_remaining / 0.72))
                        if (ray + int(blast_remaining * 120)) % 3 == 0:
                            spark_y = portal_top + (
                                ray * 37 + int(blast_remaining * 520)
                            ) % max(1, portal_bottom - portal_top)
                            pygame.draw.line(
                                boss_glass_layer, (170, 245, 255, flash),
                                (ray, max(portal_top, spark_y - 5)),
                                (ray, min(portal_bottom, spark_y + 5)), 2,
                            )
                if shortcut_view_offset is not None:
                    continue
            if wall_type == 5:
                # This collision-solid region is only a sightline through the
                # far door; it intentionally has no render depth.
                continue
            if wall_type == 4:
                corrected_depth = max(corrected_depth, 1e-6)
                wall_coordinate = hit_y if hit_side == "x" else hit_x
                local_u = wall_coordinate % TILE_SIZE
                door_height = min(
                    HEIGHT, int((TILE_SIZE / corrected_depth) * DIST_PLANE)
                )
                door_top = int(HEIGHT / 2 - door_height / 2)
                door_bottom = int(HEIGHT / 2 + door_height / 2)
                if local_u < 6.0 or local_u > TILE_SIZE - 6.0:
                    pygame.draw.line(
                        boss_glass_layer, (*BOSS_ESCAPE_FRAME_COLOR, 210),
                        (ray, door_top), (ray, door_bottom), 2,
                    )
                else:
                    lintel_bottom = min(door_bottom, door_top + max(3, door_height // 12))
                    pygame.draw.line(
                        boss_glass_layer, (*BOSS_ESCAPE_FRAME_COLOR, 210),
                        (ray, door_top), (ray, lintel_bottom), 2,
                    )
                continue
            if wall_type == 2:
                corrected_depth = max(corrected_depth, 1e-6)
                wall_coordinate = hit_y if hit_side == "x" else hit_x
                fine_period = TILE_SIZE / 16
                if hit_side == "x":
                    previous_cell = (map_x - step_x, map_y)
                else:
                    previous_cell = (map_x, map_y - step_y)
                entered_from_outside_cell = not (
                    BOSS_CORE_LEFT <= previous_cell[0] <= BOSS_CORE_LEFT + 1
                    and BOSS_CORE_TOP <= previous_cell[1] <= BOSS_CORE_TOP + 1
                )
                if (entered_from_outside_cell
                        and wall_coordinate % fine_period < 0.9):
                    glass_height = min(
                        HEIGHT, int((TILE_SIZE / corrected_depth) * DIST_PLANE)
                    )
                    glass_top = HEIGHT / 2 - glass_height / 2
                    glass_bottom = HEIGHT / 2 + glass_height / 2
                    pygame.draw.line(
                        boss_glass_layer, (255, 105, 190, 78),
                        (ray, int(glass_top)), (ray, int(glass_bottom)), 1,
                    )
                # Cell walls are visible, but deliberately do not enter the
                # wall depth buffer so the friendly spheres remain visible.
                continue
            # When the player is exactly on a grid boundary, a backwards ray
            # can hit the neighboring wall at depth zero. Treat it as an
            # immediate wall so projection stays finite and fills the view.
            corrected_depth = max(corrected_depth, 1e-6)
            wall_depths[ray] = corrected_depth
            wall_height = min(HEIGHT, int((TILE_SIZE / corrected_depth) * DIST_PLANE))
            wall_tops[ray] = max(0, int(HEIGHT / 2 - wall_height / 2))

            # DDA gives the exact face crossed, so texture coordinates stay
            # tied to the corresponding world-space wall axis.
            wall_coordinate = hit_y if hit_side == "x" else hit_x
            stripe_period = TILE_SIZE / 8
            stripe_width = stripe_period * (0.75 if wall_type == 6 else 0.25)
            draw_stripe = (wall_coordinate % stripe_period) < stripe_width

            top_y = (HEIGHT / 2) - (wall_height / 2)
            bottom_y = (HEIGHT / 2) + (wall_height / 2)

            if draw_stripe:
                wall_color = (BOSS_EXIT_COLOR if wall_type == 3
                              else wall_color_at(mapped_hit_x, mapped_hit_y))
                if wall_type == 6:
                    pulse = 0.94 + 0.06 * math.sin(pygame.time.get_ticks() * 0.003)
                    wall_color = tuple(
                        int(base * (1.0 - 0.78 * pulse) + tint * 0.78 * pulse)
                        for base, tint in zip(wall_color, (255, 55, 205))
                    )
                if hit_side == "x":
                    face_x, face_y = -step_x, 0
                else:
                    face_x, face_y = 0, -step_y

                reflected_light = 0.0
                tint_weight = [0.0, 0.0, 0.0]
                tint_contribution = 0.0
                marker_light = 0.0
                for source, source_tint, source_strength, light_radius, is_marker in wall_light_sources:
                    light_dx = source["x"] - mapped_hit_x
                    light_dy = source["y"] - mapped_hit_y
                    light_distance = math.hypot(light_dx, light_dy)
                    if light_distance <= 0:
                        continue
                    facing = max(0.0, (face_x * light_dx + face_y * light_dy) / light_distance)
                    falloff = max(0.0, 1.0 - light_distance / light_radius) ** 2
                    contribution = facing * falloff * source_strength
                    reflected_light += contribution
                    if is_marker:
                        marker_light += contribution
                    tint_contribution += contribution
                    for channel in range(3):
                        tint_weight[channel] += source_tint[channel] * contribution
                if reflected_light > 0 and marker_light <= 0:
                    reflected_light += random.uniform(-0.12, 0.12)
                reflected_light = max(0.0, min(0.82, reflected_light))
                if tint_contribution > 0:
                    plasma_tint = tuple(
                        min(255, int(value / tint_contribution))
                        for value in tint_weight
                    )
                else:
                    plasma_tint = (205, 165, 255)
                wall_color = tuple(
                    int(base * (1.0 - reflected_light) + tint * reflected_light)
                    for base, tint in zip(wall_color, plasma_tint)
                )
                pygame.draw.line(screen, wall_color, (ray, top_y), (ray, bottom_y), 1)
            break

    draw_space_stars(screen, wall_tops)
    if boss_battle_complete and boss_cage_destroyed:
        for sphere in boss_spheres:
            if sphere["beam_state"] == "beaming":
                draw_sphere_tractor_beam(
                    boss_glass_layer, sphere, wall_depths,
                    player_x, player_y, player_angle,
                )
    draw_floor_grid(screen, player_x, player_y, wall_depths)
    screen.blit(boss_glass_layer, (0, 0))

    # Draw sprites after walls, back to front. The wall depth buffer clips each
    # sprite against the maze, and painter ordering makes nearer spheres cover
    # farther spheres where their screen shapes overlap.
    visible_enemies = [
        enemy for enemy in enemies
        if not enemy["virtual"]
        and enemy.get("spawn_fx", 0.0) <= SPAWN_BEAM_LAND_REMAINING
    ]
    if boss_room_active:
        visible_enemies.extend(
            sphere for sphere in boss_spheres if sphere["beam_state"] != "gone"
        )
    visible_enemies.sort(
        key=lambda enemy: (enemy["x"] - player_x) * math.cos(player_angle)
        + (enemy["y"] - player_y) * math.sin(player_angle),
        reverse=True,
    )
    for enemy in visible_enemies:
        draw_enemy_floor_glow(
            screen, enemy, wall_depths, player_x, player_y, player_angle
        )
    for enemy in enemies:
        if enemy["virtual"] or enemy.get("spawn_fx", 0.0) <= 0.0:
            continue
        draw_enemy_spawn_portal(
            screen, enemy, wall_depths, player_x, player_y, player_angle
        )
    pickup_objects = [
        *(("armor", pickup) for pickup in armor_pickups),
        *(("health", pickup) for pickup in health_pickups),
        *(("quad", pickup) for pickup in quad_pickups),
        *(("quad_damage", pickup) for pickup in quad_damage_pickups),
        *(("super_speed", pickup) for pickup in super_speed_pickups),
    ]
    for pickup_type, pickup in pickup_objects:
        dx, dy = pickup["x"] - player_x, pickup["y"] - player_y
        distance = math.hypot(dx, dy)
        relative = (math.atan2(dy, dx) - player_angle + math.pi) % math.tau - math.pi
        depth = distance * math.cos(relative)
        if depth <= 1.0 or depth > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
            continue
        screen_x = (relative + HALF_FOV) / STEP_ANGLE
        floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / depth
        if pickup_type == "armor":
            draw_floor_reflection(
                screen, screen_x, floor_y, depth, 0.9, wall_depths,
                tint=(80, 255, 115),
            )
        elif pickup_type == "health":
            draw_floor_reflection(
                screen, screen_x, floor_y, depth, 1.1, wall_depths,
                tint=(45, 255, 100),
            )
        elif pickup_type == "super_speed":
            draw_floor_reflection(
                screen, screen_x, floor_y, depth, 1.35, wall_depths,
                tint=(65, 205, 255),
            )
        elif pickup_type == "quad_damage":
            draw_floor_reflection(
                screen, screen_x, floor_y, depth, 1.6, wall_depths,
                tint=QUAD_DAMAGE_ITEM_COLOR,
            )
        else:
            draw_floor_reflection(
                screen, screen_x, floor_y, depth, 1.4, wall_depths,
                tint=(195, 105, 255),
            )

    # Sort all billboard objects together so nearer items and enemies cover
    # farther ones instead of being layered by object category.
    render_objects = []
    for enemy in visible_enemies:
        forward = ((enemy["x"] - player_x) * math.cos(player_angle)
                   + (enemy["y"] - player_y) * math.sin(player_angle))
        render_objects.append((forward, "enemy", enemy))
    for marker in player_markers:
        forward = ((marker["x"] - player_x) * math.cos(player_angle)
                   + (marker["y"] - player_y) * math.sin(player_angle))
        render_objects.append((forward, "marker", marker))
    for pickup_type, pickup in pickup_objects:
        forward = ((pickup["x"] - player_x) * math.cos(player_angle)
                   + (pickup["y"] - player_y) * math.sin(player_angle))
        side = (-(pickup["x"] - player_x) * math.sin(player_angle)
                + (pickup["y"] - player_y) * math.cos(player_angle))
        if (1.0 < forward <= VIEW_DISTANCE_BLOCKS * TILE_SIZE
                and abs(math.atan2(side, forward)) <= HALF_FOV):
            render_objects.append((forward, pickup_type, pickup))
    render_objects.sort(key=lambda item: item[0], reverse=True)
    for _, object_type, obj in render_objects:
        if object_type == "enemy":
            if obj.get("type") == "triangle":
                draw_enemy_triangle(screen, obj, wall_depths, player_x, player_y, player_angle)
            elif obj.get("type") == "rectangle":
                draw_enemy_rectangle(screen, obj, wall_depths, player_x, player_y, player_angle)
            else:
                draw_enemy_sphere(screen, obj, wall_depths, player_x, player_y, player_angle)
        elif object_type == "marker":
            draw_player_marker(screen, obj, wall_depths, player_x, player_y, player_angle)
        elif object_type == "armor":
            draw_armor_pickup(screen, obj, wall_depths, player_x, player_y, player_angle)
        elif object_type == "health":
            draw_health_pickup(screen, obj, wall_depths, player_x, player_y, player_angle)
        elif object_type == "super_speed":
            draw_super_speed_pickup(
                screen, obj, wall_depths, player_x, player_y, player_angle
            )
        elif object_type == "quad_damage":
            draw_quad_damage_pickup(
                screen, obj, wall_depths, player_x, player_y, player_angle
            )
        else:
            draw_quad_pickup(screen, obj, wall_depths, player_x, player_y, player_angle)

    for shot in hostile_projectiles:
        draw_hostile_projectile(screen, shot, wall_depths, player_x, player_y, player_angle)
    for blast in boss_cage_blasts:
        if blast["delay"] <= 0.0:
            draw_hostile_projectile(
                screen, blast, wall_depths, player_x, player_y, player_angle
            )


    # Project the plasma source onto the ground plane to create a soft floor
    # reflection. The depth buffer clips the glow where a nearer wall blocks it.
    for projectile in projectiles:
        dx = projectile["x"] - player_x
        dy = projectile["y"] - player_y
        distance = math.hypot(dx, dy)
        angle_to_source = math.atan2(dy, dx)
        relative = (angle_to_source - player_angle + math.pi) % (2 * math.pi) - math.pi
        depth = distance * math.cos(relative)
        if depth <= 1 or abs(relative) > HALF_FOV:
            continue
        screen_x = (relative + HALF_FOV) / STEP_ANGLE
        floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / depth
        glow_strength = 0.9
        if projectile["explosion"] > 0:
            glow_strength = 1.4 + 0.7 * (
                1.0 - projectile["explosion"] / PLASMA_EXPLOSION_DURATION
            )
        if projectile.get("marker_projectile"):
            glow_strength *= 2.0
        if projectile.get("quad_damage"):
            glow_strength *= 4.0
        draw_floor_reflection(
            screen, screen_x, floor_y, depth, glow_strength, wall_depths,
            tint=projectile.get(
                "explosion_color",
                projectile.get("weapon_color", PLASMA_EXPLOSION_TINT),
            ),
        )

    # Stuck markers remain active light sources: cast a broad yellow pool
    # onto the floor and let their light tint nearby wall faces above.
    for marker in player_markers:
        dx, dy = marker["x"] - player_x, marker["y"] - player_y
        distance = math.hypot(dx, dy)
        relative = (math.atan2(dy, dx) - player_angle + math.pi) % math.tau - math.pi
        depth = distance * math.cos(relative)
        if depth <= 1 or abs(relative) > HALF_FOV:
            continue
        screen_x = (relative + HALF_FOV) / STEP_ANGLE
        floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / depth
        # Pull the projected light just in front of the wall plane, so the
        # wall holding the marker does not occlude its own floor reflection.
        draw_floor_reflection(
            screen, screen_x, floor_y, max(1.0, depth - 32.0), 2.4,
            wall_depths, tint=(255, 225, 35), noise_density=0.12,
        )

    for shot in hostile_projectiles:
        dx, dy = shot["x"] - player_x, shot["y"] - player_y
        distance = math.hypot(dx, dy)
        relative = (math.atan2(dy, dx) - player_angle + math.pi) % math.tau - math.pi
        depth = distance * math.cos(relative)
        if depth <= 1 or abs(relative) > HALF_FOV:
            continue
        screen_x = (relative + HALF_FOV) / STEP_ANGLE
        floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / depth
        glow_strength = 0.85
        if shot["explosion"] > 0:
            glow_strength = 1.7 + 0.8 * (
                1.0 - shot["explosion"] / PLASMA_EXPLOSION_DURATION
            )
        draw_floor_reflection(
            screen, screen_x, floor_y, depth, glow_strength, wall_depths,
            tint=shot.get("plasma_color", (70, 155, 255)
                           if shot.get("blue_cannon") else (255, 58, 38)),
            noise_density=0.12,
        )

    # Project each ball into the view. The small world-space radius keeps a
    # newly fired ball compact; perspective enlarges it as it approaches.
    for projectile in projectiles:
        offset_x = projectile["x"] - player_x
        offset_y = projectile["y"] - player_y
        distance = math.hypot(offset_x, offset_y)
        world_angle = math.atan2(offset_y, offset_x)
        relative_angle = (world_angle - player_angle + math.pi) % (2 * math.pi) - math.pi
        depth = distance * math.cos(relative_angle)
        if depth <= 1 or abs(relative_angle) > HALF_FOV:
            continue
        screen_x = (relative_angle + HALF_FOV) / STEP_ANGLE
        center_y = HEIGHT / 2
        if projectile["explosion"] > 0:
            progress = 1.0 - projectile["explosion"] / PLASMA_EXPLOSION_DURATION
            radius_world = (3.0 + progress
                            * (42.0 if projectile.get("enemy_kill") else 18.0)) * 1.25
        else:
            radius_world = 3.0
        if projectile.get("marker_projectile"):
            radius_world *= 2.0
        if projectile.get("quad_damage"):
            radius_world *= 2.0
        radius = max(2, int(radius_world * DIST_PLANE / depth))
        diameter = max(2, radius * 2)
        if projectile.get("explosion", 0.0) > 0.0:
            if projectile.get("enemy_kill"):
                source_texture = make_enemy_explosion_texture(projectile["explosion_color"])
            else:
                source_texture = make_colored_plasma_texture(
                    projectile.get("weapon_color", PLASMA_EXPLOSION_TINT)
                )
        else:
            source_texture = make_colored_plasma_texture(
                projectile.get("weapon_color", PLASMA_EXPLOSION_TINT)
            )
        if projectile.get("enemy_kill"):
            energy_sprite = pygame.transform.smoothscale(source_texture, (diameter, diameter))
        else:
            energy_sprite = make_scaled_plasma_texture(
                projectile.get("weapon_color", PLASMA_EXPLOSION_TINT), diameter
            )
        left = max(0, int(screen_x) - radius)
        right = min(WIDTH - 1, int(screen_x) + radius)
        for x in range(left, right + 1):
            if depth >= wall_depths[x]:
                continue
            source_x = x - (int(screen_x) - radius)
            if 0 <= source_x < diameter:
                column = energy_sprite.subsurface((source_x, 0, 1, diameter))
                position = (x, int(center_y) - radius)
                screen.blit(column, position)
                if projectile.get("marker_projectile"):
                    screen.blit(column, position, special_flags=pygame.BLEND_RGBA_ADD)
                elif projectile.get("quad_damage"):
                    for _ in range(3):
                        screen.blit(column, position,
                                    special_flags=pygame.BLEND_RGBA_ADD)

    if rectangle_spawn_flash > 0.0:
        flash_progress = 1.0 - rectangle_spawn_flash / 0.34
        flash_pulse = 0.5 + 0.5 * math.cos(flash_progress * math.tau)
        flash_alpha = int(185 * flash_pulse * (1.0 - 0.65 * flash_progress))
        screen_grain.fill((255, 248, 240, flash_alpha))
        screen.blit(screen_grain, (0, 0))
    if player_hit_flash > 0.0:
        red_flash_alpha = int(64 * min(1.0, player_hit_flash / 0.22))
        screen_grain.fill((255, 72, 66, red_flash_alpha))
        screen.blit(screen_grain, (0, 0))

    # Add an extra pass over visible geometry before the full-screen grain.
    # Skipping the near-black clear color keeps this pass concentrated on
    # wall lines, enemy spheres, and the other rendered light sources.
    screen_grain.fill((0, 0, 0, 0))
    damage_noise_scale = 1.0 + player_damage * 0.20
    noise_count = 5000
    if player_damage >= 7:
        final_stages = player_damage - 6
        damage_noise_scale = 2.2 + final_stages * 1.6
        noise_count = 5000 + final_stages * 1750
    base_grain_colors = ((220, 205, 255), (170, 115, 255), (255, 255, 255), (130, 70, 220))
    hurt_grain_colors = ((255, 35, 25), (255, 95, 18), (255, 175, 54), (195, 8, 18))
    damage_tint = min(1.0, player_damage / 10.0)
    grain_colors = tuple(
        tuple(int(base * (1.0 - damage_tint) + hurt * damage_tint)
              for base, hurt in zip(base_color, hurt_color))
        for base_color, hurt_color in zip(base_grain_colors, hurt_grain_colors)
    )
    if triangle_spawn_flash > 0.0:
        grain_colors = ((255, 245, 65), (255, 220, 25), (255, 255, 170), (235, 180, 12))
        damage_noise_scale = max(damage_noise_scale, 2.5)
    elif sphere_spawn_flash > 0.0:
        grain_colors = ((220, 205, 255), (170, 115, 255), (255, 255, 255), (130, 70, 220))
        damage_noise_scale = max(damage_noise_scale, 2.3)
    if player_hit_flash > 0.0:
        grain_colors = ((255, 45, 18), (255, 95, 14), (255, 175, 54), (210, 12, 24))
        damage_noise_scale = max(damage_noise_scale, 3.8)
    if armor_hits_remaining > 0:
        grain_colors = ((70, 255, 105), (24, 190, 82), (220, 255, 225), (16, 120, 58))
    for _ in range(noise_count):
        x = random.randrange(WIDTH)
        y = random.randrange(HEIGHT)
        if max(screen.get_at((x, y))[:3]) <= 14:
            continue
        color = random.choice(grain_colors)
        alpha = min(255, int(random.randint(22, 88) * damage_noise_scale))
        pygame.draw.line(screen_grain, (*color, alpha), (x, y), (x, y))
    screen.blit(screen_grain, (0, 0))

    # Full-screen film grain using the same purple and white static palette
    # as the plasma reflections. Re-sample it each frame for a subtle shimmer.
    screen_grain.fill((0, 0, 0, 0))
    for _ in range(noise_count):
        x = random.randrange(WIDTH)
        y = random.randrange(HEIGHT)
        color = random.choice(grain_colors)
        alpha = min(255, int(random.randint(20, 60) * damage_noise_scale))
        pygame.draw.line(screen_grain, (*color, alpha), (x, y), (x, y))
    screen.blit(screen_grain, (0, 0))

    boss_enemy = next((enemy for enemy in enemies if enemy.get("boss")), None)
    if boss_room_active and boss_enemy is not None:
        boss_name_font = pygame.font.SysFont("monospace", max(14, HEIGHT // 32), bold=True)
        boss_name_surface = boss_name_font.render(BOSS_NAME, True, (255, 128, 194))
        boss_name_x = (WIDTH - boss_name_surface.get_width()) // 2
        boss_name_y = max(8, HEIGHT // 48)
        screen.blit(boss_name_surface, (boss_name_x, boss_name_y))
        health_bar_width = min(int(WIDTH * 0.48), 520)
        health_bar_height = max(10, HEIGHT // 42)
        health_bar_x = (WIDTH - health_bar_width) // 2
        health_bar_y = boss_name_y + boss_name_surface.get_height() + 5
        pygame.draw.rect(
            screen, (24, 8, 18),
            (health_bar_x, health_bar_y, health_bar_width, health_bar_height),
        )
        health_fraction = max(
            0.0, 1.0 - boss_enemy.get("hits", 0) / BOSS_MAX_HEALTH
        )
        pygame.draw.rect(
            screen, (255, 58, 132),
            (health_bar_x, health_bar_y,
             int(health_bar_width * health_fraction), health_bar_height),
        )
        pygame.draw.rect(
            screen, (255, 205, 230),
            (health_bar_x, health_bar_y, health_bar_width, health_bar_height), 2,
        )

    if args.debug and not title_screen:
        debug_font = pygame.font.SysFont("monospace", max(12, HEIGHT // 48), bold=True)
        debug_lines = [
            f"WORLD: X {player_x:.1f}  Y {player_y:.1f}",
            f"HEALTH: {max(0, 10 - player_damage)}/10",
            f"WEAPON: {('B', 'A', 'S')[player_weapon_level]}  POINTS: {weapon_points}/20",
            f"POWERUPS: SPEED {super_speed_timer:.1f}s  QUAD {quad_damage_timer:.1f}s",
            f"ENEMIES: {len(enemies)}  ARMOR: {armor_hits_remaining}/{MAX_ARMOR_HITS}  NOCLIP: {'ON' if debug_noclip else 'OFF'}  INVULN: {'ON' if debug_invulnerable else 'OFF'}",
        ]
        for index, enemy in enumerate(enemies):
            enemy_type = enemy.get("type", "enemy").upper()
            if enemy.get("virtual"):
                state = f"DESPAWNED {enemy.get('virtual_eta', 0.0):.1f}s"
            elif enemy.get("spawn_fx", 0.0) > SPAWN_BEAM_LAND_REMAINING:
                state = f"SPAWNING {enemy.get('spawn_fx', 0.0):.1f}s"
            else:
                state = "ACTIVE"
            if enemy_type == "RECTANGLE":
                if enemy.get("blue_cannon"):
                    state += "  BLUE CANNON"
                state += f"  SHOT {enemy.get('shot_timer', 0.0):.1f}s"
            debug_lines.append(f"{index + 1}. {enemy_type}: {state}")
        debug_line_height = debug_font.get_linesize()
        for line_index, line in enumerate(debug_lines):
            label = debug_font.render(line, True, (255, 255, 255))
            screen.blit(label, (10, 10 + line_index * debug_line_height))

    if game_over:
        if game_over_scene is None:
            game_over_scene = screen.copy()
        screen.blit(game_over_title, (0, 0))

    if title_screen and title_map_visible and title_map_surface is not None:
        screen.fill((3, 7, 6))
        map_title_font = pygame.font.SysFont("monospace", max(18, HEIGHT // 24), bold=True)
        map_hint_font = pygame.font.SysFont("monospace", max(11, HEIGHT // 46), bold=True)
        map_title = map_title_font.render("SEEDED MAZE MAP", True, (235, 255, 240))
        map_seed = map_hint_font.render(f"SEED {WORLD_SEED}", True, (90, 255, 145))
        map_hint = map_hint_font.render("W A S D // PAN     SPACE // RETURN", True,
                                        (235, 255, 240))
        screen.blit(map_title, ((WIDTH - map_title.get_width()) // 2, 8))
        screen.blit(map_seed, ((WIDTH - map_seed.get_width()) // 2,
                               12 + map_title.get_height()))
        margin = max(12, HEIGHT // 30)
        map_top = 20 + map_title.get_height() + map_seed.get_height()
        map_bottom = HEIGHT - map_hint.get_height() - margin * 2
        map_size = max(1, min(WIDTH - margin * 2, map_bottom - map_top))
        crop_width = max(1, title_map_surface.get_width() // TITLE_MAP_ZOOM)
        crop_height = max(1, title_map_surface.get_height() // TITLE_MAP_ZOOM)
        crop_left = int(round(title_map_center[0] - crop_width / 2))
        crop_top = int(round(title_map_center[1] - crop_height / 2))
        crop_left = max(0, min(title_map_surface.get_width() - crop_width, crop_left))
        crop_top = max(0, min(title_map_surface.get_height() - crop_height, crop_top))
        map_view = title_map_surface.subsurface(
            pygame.Rect(crop_left, crop_top, crop_width, crop_height)
        )
        rendered_map = pygame.transform.scale(map_view, (map_size, map_size))
        map_rect = rendered_map.get_rect(center=(WIDTH // 2,
                                                 (map_top + map_bottom) // 2))
        pygame.draw.rect(screen, (70, 255, 130), map_rect.inflate(6, 6), 2)
        screen.blit(rendered_map, map_rect)
        screen.blit(map_hint, ((WIDTH - map_hint.get_width()) // 2,
                               HEIGHT - map_hint.get_height() - margin))
    elif title_screen:
        if attract_mode:
            draw_attract_screen(screen, pygame.time.get_ticks() - attract_started)
        else:
            screen.blit(start_title, (0, 0))
            beat_ms = MUSIC_BEAT_SECONDS * 1000.0
            beat_phase = (pygame.time.get_ticks() - title_music_started) % beat_ms
            if beat_phase < beat_ms * 0.68:
                prompt_x = (WIDTH - start_prompt.get_width()) // 2
                prompt_y = int(HEIGHT * 0.79)
                screen.blit(start_prompt, (prompt_x, prompt_y))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
