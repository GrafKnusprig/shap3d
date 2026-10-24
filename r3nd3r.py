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
    "--print-map", nargs="?", const="world_map.png", metavar="PNG",
    help="save a 1000x1000 PNG of the starting area (default: world_map.png)",
)
def parse_map_size(value):
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("map size must be WIDTHxHEIGHT, for example 1000x800")
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("map width and height must be positive")
    return width, height

parser.add_argument(
    "--map-size", type=parse_map_size, default=(1000, 1000), metavar="WIDTHxHEIGHT",
    help="set the printed map dimensions in pixels (default: 1000x1000)",
)
parser.add_argument(
    "--super-resolution", action="store_true",
    help="draw one pixel per world block and omit the player marker",
)
parser.add_argument("--seed", type=int, help="set the world seed for a reproducible map or game")
args = parser.parse_args()

# Initialize Pygame
pygame.mixer.pre_init(22050, -16, 1, 1024)
pygame.init()
if args.print_map is not None:
    WIDTH, HEIGHT = 1000, 1000
    screen = pygame.Surface((WIDTH, HEIGHT))
else:
    screen = pygame.display.set_mode(
        (640, 480), pygame.FULLSCREEN | pygame.SCALED, vsync=1
    )
    pygame.mouse.set_visible(False)
    WIDTH, HEIGHT = screen.get_size()
clock = pygame.time.Clock()
screen_grain = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

def make_energy_texture(size=96):
    """Build a noisy, mostly-white energy sphere with a faint violet edge."""
    rng = random.Random(19)
    texture = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            nx = (x - center) / center
            ny = (y - center) / center
            radius = math.sqrt(nx * nx + ny * ny)
            if radius >= 1:
                continue

            edge = max(0.0, min(1.0, (radius - 0.48) / 0.52))
            noise = rng.uniform(-13, 9)
            purple = edge * 30 + rng.uniform(0, 8)
            brightness = max(0, min(255, int(255 - edge * 12 + noise)))
            red = brightness
            green = max(0, int(brightness - purple * 0.45))
            blue = max(0, int(brightness - purple * 0.08))
            alpha = int(255 * min(1.0, (1 - radius) * 8))

            # A few dim violet specks break up the smooth surface.
            if rng.random() < 0.035:
                red = max(0, red - rng.randint(10, 35))
                green = max(0, green - rng.randint(18, 55))
                blue = max(0, blue - rng.randint(0, 10))
            texture.set_at((x, y), (red, green, blue, alpha))
    return texture

ENERGY_TEXTURE = make_energy_texture()


@lru_cache(maxsize=16)
def make_floor_reflection_gradient(strength_step):
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
            red = int(145 + (245 - 145) * center_mix)
            green = int(75 + (220 - 75) * center_mix)
            blue = int(235 + (255 - 235) * center_mix)
            alpha = min(220, int(65 * strength * falloff))
            gradient.set_at((x, y), (red, green, blue, alpha))
    return gradient


def draw_floor_reflection(target, screen_x, floor_y, depth, strength, wall_depths):
    """Draw a soft, perspective-scaled plasma glow onto the visible floor."""
    if depth <= 1:
        return
    radius_x = max(3, min(WIDTH // 2, int(58 * DIST_PLANE / depth)))
    radius_y = max(3, min(34, int(8 * DIST_PLANE / depth)))
    strength_step = max(1, int(round(strength * 10)))
    glow = pygame.transform.smoothscale(
        make_floor_reflection_gradient(strength_step),
        (radius_x * 2, radius_y * 2),
    )

    # Increase the static with the light strength so bright explosions keep
    # their edges noisy instead of exposing the layered ellipse shapes.
    noise_scale = max(1.0, strength / 0.9)
    for _ in range(int(150 * noise_scale)):
        noise_x = random.randrange(radius_x * 2)
        noise_y = random.randrange(radius_y * 2)
        nx = (noise_x - radius_x) / radius_x
        ny = (noise_y - radius_y) / radius_y
        if nx * nx + ny * ny > 1 or random.random() < 0.12:
            continue
        noise_color = random.choice(((220, 205, 255), (170, 115, 255), (255, 255, 255), (130, 70, 220)))
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
    if depth <= 1 or abs(relative) > HALF_FOV:
        return

    screen_x = WIDTH / 2 + math.tan(relative) * DIST_PLANE
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
VIEW_DISTANCE_BLOCKS = 12
CHUNK_SIZE = 32
MAZE_NODES_PER_SIDE = 5
MAZE_NODE_SPACING = 6
WORLD_MASK = (1 << 64) - 1
WORLD_SEED = (args.seed & WORLD_MASK) if args.seed is not None else random.SystemRandom().getrandbits(64)


def world_hash(cell_x, cell_y):
    """Return a stable pseudo-random value for a world cell this run."""
    value = (WORLD_SEED ^ ((cell_x & WORLD_MASK) * 0x9E3779B185EBCA87)
             ^ ((cell_y & WORLD_MASK) * 0xC2B2AE3D27D4EB4F)) & WORLD_MASK
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & WORLD_MASK
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & WORLD_MASK
    return value ^ (value >> 31)


def vertical_door_index(edge_x, chunk_y):
    """Choose the shared north/south position for a vertical chunk seam."""
    return world_hash(edge_x * 2, chunk_y * 2 + 1) % MAZE_NODES_PER_SIDE


def horizontal_door_index(chunk_x, edge_y):
    """Choose the shared east/west position for a horizontal chunk seam."""
    return world_hash(chunk_x * 2 + 1, edge_y * 2) % MAZE_NODES_PER_SIDE


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

    # Open each maze cell, with an occasional 4x4 chamber around a node.
    for node_x, node_y in visited:
        center_x, center_y = node_center((node_x, node_y))
        global_node_x = chunk_x * node_count + node_x
        global_node_y = chunk_y * node_count + node_y
        has_chamber = world_hash(global_node_x, global_node_y) % 23 == 0
        if has_chamber:
            for local_y in range(center_y - 1, center_y + 3):
                for local_x in range(center_x - 1, center_x + 3):
                    open_blocks.add((local_x, local_y))
        else:
            open_blocks.add((center_x, center_y))

    # Carve the one-block-wide corridors selected by DFS.
    for first, second in passages:
        x1, y1 = node_center(first)
        x2, y2 = node_center(second)
        if y1 == y2:
            for local_x in range(min(x1, x2), max(x1, x2) + 1):
                open_blocks.add((local_x, y1))
        else:
            for local_y in range(min(y1, y2), max(y1, y2) + 1):
                open_blocks.add((x1, local_y))

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


def world_block(cell_x, cell_y):
    """Regenerate a block from the run seed and its chunk coordinates."""
    chunk_x, local_x = divmod(cell_x, CHUNK_SIZE)
    chunk_y, local_y = divmod(cell_y, CHUNK_SIZE)
    return 0 if (local_x, local_y) in generate_maze_chunk(chunk_x, chunk_y) else 1


def generate_map_region(left_cell, top_cell, width, height):
    """Regenerate a rectangular map region, caching each touched chunk once."""
    chunk_cache = {}
    visible = {}
    for cell_y in range(top_cell, top_cell + height):
        for cell_x in range(left_cell, left_cell + width):
            chunk_x, local_x = divmod(cell_x, CHUNK_SIZE)
            chunk_y, local_y = divmod(cell_y, CHUNK_SIZE)
            chunk_key = (chunk_x, chunk_y)
            if chunk_key not in chunk_cache:
                chunk_cache[chunk_key] = generate_maze_chunk(chunk_x, chunk_y)
            visible[(cell_x, cell_y)] = 0 if (local_x, local_y) in chunk_cache[chunk_key] else 1
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
    """Move slowly around the hue wheel as walls get farther from world zero."""
    distance = math.hypot(world_x, world_y)
    hue = (1.0 / 3.0 + distance / (TILE_SIZE * 180.0)) % 1.0
    rgb = colorsys.hsv_to_rgb(hue, 0.95, 1.0)
    return tuple(int(channel * 255) for channel in rgb)


def find_spawn_cell():
    """Find the closest open block to world origin for a safe start."""
    origin_chunk = generate_maze_chunk(0, 0)
    return min(origin_chunk, key=lambda cell: cell[0] ** 2 + cell[1] ** 2)


def hall_at_cell(cell_x, cell_y):
    """Return the stable hall ID when a world cell lies inside a 4x4 hall."""
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
    if world_hash(global_node_x, global_node_y) % 23 != 0:
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


# def line_is_open(x1, y1, x2, y2):
#     distance = math.hypot(x2 - x1, y2 - y1)
#     steps = max(1, int(distance / 8))
#     for step in range(1, steps):
#         ratio = step / steps
#         if world_block(
#             math.floor((x1 + (x2 - x1) * ratio) / TILE_SIZE),
#             math.floor((y1 + (y2 - y1) * ratio) / TILE_SIZE),
#         ) != 0:
#             return False
#     return True
#
#
# def find_spider_spawn(world_x, world_y, facing):
#     """Find an open, visible maze block a few steps ahead of the player."""
#     start = (math.floor(world_x / TILE_SIZE), math.floor(world_y / TILE_SIZE))
#     queue = [(start, 0)]
#     seen = {start}
#     candidates = []
#     cursor = 0
#     directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
#     while cursor < len(queue):
#         (cell_x, cell_y), path_length = queue[cursor]
#         cursor += 1
#         center_x = (cell_x + 0.5) * TILE_SIZE
#         center_y = (cell_y + 0.5) * TILE_SIZE
#         dx, dy = center_x - world_x, center_y - world_y
#         forward = dx * math.cos(facing) + dy * math.sin(facing)
#         side = -dx * math.sin(facing) + dy * math.cos(facing)
#         if 2 <= path_length <= 7 and TILE_SIZE * 1.5 <= forward <= TILE_SIZE * 7:
#             in_front_cone = abs(side) <= forward * math.tan(HALF_FOV) * 0.6
#             if in_front_cone and line_is_open(world_x, world_y, center_x, center_y):
#                 score = abs(forward - TILE_SIZE * 3.5) + abs(side) * 1.5
#                 candidates.append((score, center_x, center_y))
#         if path_length >= 7:
#             continue
#         for step_x, step_y in directions:
#             next_cell = (cell_x + step_x, cell_y + step_y)
#             if next_cell not in seen and world_block(*next_cell) == 0:
#                 seen.add(next_cell)
#                 queue.append((next_cell, path_length + 1))
#
#     if candidates:
#         _, spider_x, spider_y = min(candidates)
#         return spider_x, spider_y
#     # The maze is connected, so this fallback still puts the spider on-path.
#     (cell_x, cell_y), _ = max(queue[1:], key=lambda item: item[1])
#     return (cell_x + 0.5) * TILE_SIZE, (cell_y + 0.5) * TILE_SIZE
#
#
# def choose_spider_target(spider):
#     """Choose a neighboring open block, avoiding an immediate reversal."""
#     cell_x = math.floor(spider["x"] / TILE_SIZE)
#     cell_y = math.floor(spider["y"] / TILE_SIZE)
#     current = (cell_x, cell_y)
#     options = []
#     for step_x, step_y in ((1, 0), (0, 1), (-1, 0), (0, -1)):
#         neighbor = (cell_x + step_x, cell_y + step_y)
#         if world_block(*neighbor) == 0:
#             options.append(neighbor)
#     forward_options = [cell for cell in options if cell != spider.get("previous_cell")]
#     if forward_options:
#         options = forward_options
#     if not options:
#         return
#
#     pick = world_hash(cell_x + 7919, cell_y - 104729) % len(options)
#     target_cell = options[pick]
#     spider["previous_cell"] = current
#     spider["target"] = ((target_cell[0] + 0.5) * TILE_SIZE,
#                         (target_cell[1] + 0.5) * TILE_SIZE)
#
#
# def update_spider(spider, delta_time):
#     """Walk slowly from block center to block center through open passages."""
#     remaining = 22.0 * delta_time
#     while remaining > 0:
#         if spider["target"] is None:
#             choose_spider_target(spider)
#             if spider["target"] is None:
#                 return
#         target_x, target_y = spider["target"]
#         dx, dy = target_x - spider["x"], target_y - spider["y"]
#         distance = math.hypot(dx, dy)
#         if distance <= remaining:
#             spider["x"], spider["y"] = target_x, target_y
#             spider["heading"] = math.atan2(dy, dx)
#             remaining -= distance
#             spider["target"] = None
#         else:
#             spider["heading"] = math.atan2(dy, dx)
#             spider["x"] += dx / distance * remaining
#             spider["y"] += dy / distance * remaining
#             remaining = 0
#
#
# def project_world_point(world_x, world_y, height, player_x, player_y, player_angle):
#     dx, dy = world_x - player_x, world_y - player_y
#     forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
#     if forward <= 1:
#         return None
#     side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
#     screen_x = WIDTH / 2 + side * DIST_PLANE / forward
#     screen_y = HEIGHT / 2 + (TILE_SIZE / 2 - height) * DIST_PLANE / forward
#     return screen_x, screen_y, forward
#
#
# def draw_spider(target, spider, wall_depths, player_x, player_y, player_angle):
#     """Draw a small neon wireframe spider with world-position gait motion."""
#     body = project_world_point(spider["x"], spider["y"], 12, player_x, player_y, player_angle)
#     if body is None:
#         return
#     screen_x, screen_y, depth = body
#     column = int(screen_x)
#     if not 0 <= column < WIDTH or depth >= wall_depths[column]:
#         return
#     if abs(screen_x - WIDTH / 2) > DIST_PLANE * math.tan(HALF_FOV):
#         return
#
#     color = (255, 90, 150)
#     heading = spider["heading"]
#     gait = (spider["x"] * math.cos(heading) + spider["y"] * math.sin(heading)) * 0.12
#     body_scale = DIST_PLANE / depth
#
#     # Four legs swing from a phase tied to world position, so movement drives gait.
#     leg_angles = (-0.72, 0.72, math.pi - 0.72, math.pi + 0.72)
#     for leg_index, base_angle in enumerate(leg_angles):
#         phase = gait + leg_index * math.pi
#         leg_angle = heading + base_angle + math.sin(phase) * 0.25
#         foot_reach = 13 + 3 * math.cos(phase)
#         foot_x = spider["x"] + math.cos(leg_angle) * foot_reach
#         foot_y = spider["y"] + math.sin(leg_angle) * foot_reach
#         anchor_x = spider["x"] + math.cos(leg_angle) * 3
#         anchor_y = spider["y"] + math.sin(leg_angle) * 3
#         anchor = project_world_point(anchor_x, anchor_y, 10, player_x, player_y, player_angle)
#         foot = project_world_point(foot_x, foot_y, 0, player_x, player_y, player_angle)
#         if anchor is None or foot is None:
#             continue
#         anchor_screen_x, anchor_screen_y, _ = anchor
#         foot_x_screen, foot_y_screen, foot_depth = foot
#         foot_column = int(foot_x_screen)
#         if 0 <= foot_column < WIDTH and foot_depth < wall_depths[foot_column]:
#             pygame.draw.line(target, color, (anchor_screen_x, anchor_screen_y),
#                              (foot_x_screen, foot_y_screen), max(1, int(body_scale)))
#
#     # The abdomen is an ellipse and the thorax/head is a circle.
#     abdomen_x = spider["x"] - math.cos(heading) * 5
#     abdomen_y = spider["y"] - math.sin(heading) * 5
#     abdomen = project_world_point(abdomen_x, abdomen_y, 12, player_x, player_y, player_angle)
#     if abdomen is not None:
#         ax, ay, ad = abdomen
#         aw, ah = max(3, int(14 * DIST_PLANE / ad)), max(2, int(8 * DIST_PLANE / ad))
#         pygame.draw.ellipse(target, color, (int(ax - aw / 2), int(ay - ah / 2), aw, ah), max(1, int(body_scale)))
#     head_x = spider["x"] + math.cos(heading) * 3
#     head_y = spider["y"] + math.sin(heading) * 3
#     head = project_world_point(head_x, head_y, 12, player_x, player_y, player_angle)
#     if head is not None:
#         hx, hy, hd = head
#         pygame.draw.circle(target, color, (int(hx), int(hy)), max(2, int(3 * DIST_PLANE / hd)), max(1, int(body_scale)))
#
#
FOV = 2 * math.pi / 3  # 120 degrees Field of View
HALF_FOV = FOV / 2
NUM_RAYS = WIDTH  # One ray per column
STEP_ANGLE = FOV / NUM_RAYS
DIST_PLANE = (WIDTH / 2) / math.tan(HALF_FOV)

ENEMY_RADIUS = 18.0
ENEMY_SPEED = 42.0
ENEMY_STOP_DISTANCE = 78.0
ENEMY_MAX_TRAVEL_SECONDS = 60.0
ENEMY_MAX_PATH_STEPS = math.ceil(ENEMY_SPEED * ENEMY_MAX_TRAVEL_SECONDS / TILE_SIZE)
ENEMY_ENTRY_DISTANCE_CELLS = 8
ENEMY_REMOTE_DISTANCE = 9 * TILE_SIZE
ENEMY_PATH_REFRESH = 0.3


@lru_cache(maxsize=256)
def make_enemy_texture(base_color, light_bucket, size=24):
    """Build a tiny cel-shaded sphere lit toward the world origin."""
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


def spawn_hall_enemies(enemies, hall_id):
    """Create three to five seeded sphere enemies in a newly entered hall."""
    cells = hall_cells(hall_id)
    if not cells:
        return
    rng = random.Random(world_hash(hall_id[0] + 31337, hall_id[1] - 27183))
    for cell_x, cell_y in rng.sample(cells, min(rng.randint(3, 5), len(cells))):
        hue = rng.random()
        color = tuple(int(channel * 255) for channel in colorsys.hsv_to_rgb(hue, 0.78, 1.0))
        enemies.append({
            "x": (cell_x + 0.5) * TILE_SIZE,
            "y": (cell_y + 0.5) * TILE_SIZE,
            "color": color,
            "virtual": False,
            "path_timer": 0.0,
            "next_cell": None,
            "virtual_origin": None,
            "virtual_eta": 0.0,
            "virtual_target_eta": None,
            "virtual_refresh": 0.0,
            "entry_cell": None,
            "hits": 0,
        })


def enemy_path(enemy, player_cell):
    if enemy["virtual"]:
        start_cell = enemy["virtual_origin"]
    else:
        start_cell = (math.floor(enemy["x"] / TILE_SIZE), math.floor(enemy["y"] / TILE_SIZE))
    return find_maze_path(start_cell, player_cell, ENEMY_MAX_PATH_STEPS)


def set_virtual_approach(enemy, path):
    """Track arrival time and the maze cell where the enemy re-enters view."""
    steps = len(path) - 1
    travel_seconds = steps * TILE_SIZE / ENEMY_SPEED
    if travel_seconds > ENEMY_MAX_TRAVEL_SECONDS:
        return False
    entry_steps = max(0, steps - ENEMY_ENTRY_DISTANCE_CELLS)
    target_eta = entry_steps * TILE_SIZE / ENEMY_SPEED
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
    cells_per_second = ENEMY_SPEED / TILE_SIZE
    survivors = []
    for enemy in enemies:
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
        if player_distance > ENEMY_REMOTE_DISTANCE:
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
        move_distance = min(distance, ENEMY_SPEED * delta_time)
        if distance > 0.0 and move_distance > 0.0:
            enemy["x"] += dx / distance * move_distance
            enemy["y"] += dy / distance * move_distance
        survivors.append(enemy)
    enemies[:] = survivors


def draw_enemy_sphere(target, enemy, wall_depths, player_x, player_y, player_angle):
    """Scale a low-resolution sphere sprite and clip columns behind walls."""
    dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    if forward <= ENEMY_RADIUS + 1.0 or forward > VIEW_DISTANCE_BLOCKS * TILE_SIZE:
        return

    radius = ENEMY_RADIUS
    center_z = radius - TILE_SIZE / 2
    bearing = math.atan2(side, forward)
    center_screen_x = (bearing + HALF_FOV) / STEP_ANGLE
    center_screen_y = HEIGHT / 2 - center_z * DIST_PLANE / forward
    camera_distance = math.sqrt(forward * forward + side * side + center_z * center_z)
    angular_radius = math.asin(min(0.999, radius / camera_distance))
    sprite_width = max(2, int(2 * angular_radius / STEP_ANGLE))
    sprite_height = max(2, int(2 * radius * DIST_PLANE / forward))
    left = int(center_screen_x - sprite_width / 2)
    top = int(center_screen_y - sprite_height / 2)
    visible_left = max(0, left)
    visible_right = min(WIDTH, left + sprite_width)
    visible_top = max(0, top)
    visible_bottom = min(HEIGHT, top + sprite_height)
    if visible_left >= visible_right or visible_top >= visible_bottom:
        return

    # The apparent light direction is the bearing from this enemy to the
    # world origin, rotated into the camera's horizontal coordinate frame.
    origin_angle = math.atan2(-enemy["y"], -enemy["x"])
    relative_light_angle = (origin_angle - player_angle) % math.tau
    light_bucket = int(round(relative_light_angle * 64 / math.tau)) % 64
    texture = make_enemy_texture(enemy["color"], light_bucket)
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
    sphere_constant = forward * forward + side * side + center_z * center_z - radius * radius
    for screen_x in range(visible_left, visible_right):
        ray_relative_angle = -HALF_FOV + screen_x * STEP_ANGLE
        horizontal_slope = math.tan(ray_relative_angle)
        a = 1.0 + horizontal_slope * horizontal_slope
        half_b = -(forward + horizontal_slope * side)
        discriminant = half_b * half_b - a * sphere_constant
        if discriminant < 0.0:
            continue
        depth = (-half_b - math.sqrt(discriminant)) / a
        if depth <= 0.0 or depth >= wall_depths[screen_x]:
            continue
        source_rect_y.x = screen_x - visible_left
        target.blit(sprite, (screen_x, visible_top), source_rect_y)


# Player Parameters
spawn_cell_x, spawn_cell_y = find_spawn_cell()
player_x = (spawn_cell_x + 0.5) * TILE_SIZE
player_y = (spawn_cell_y + 0.5) * TILE_SIZE
player_angle = 0.0
# spider_x, spider_y = find_spider_spawn(player_x, player_y, player_angle)
# spider = {
#     "x": spider_x,
#     "y": spider_y,
#     "heading": player_angle,
#     "target": None,
#     "previous_cell": None,
# }
projectiles = []
enemies = []
player_hall_id = None

def print_map_png(filename, image_size):
    """Save a top-down view of the seeded map around the starting position."""
    image_width, image_height = image_size
    pixels_per_block = 1 if args.super_resolution else 8
    blocks_wide = math.ceil(image_width / pixels_per_block)
    blocks_high = math.ceil(image_height / pixels_per_block)
    center_x = math.floor(player_x / TILE_SIZE)
    center_y = math.floor(player_y / TILE_SIZE)
    left_cell = center_x - blocks_wide // 2
    top_cell = center_y - blocks_high // 2
    visible = generate_map_region(left_cell, top_cell, blocks_wide, blocks_high)

    map_image = pygame.Surface((image_width, image_height))
    map_image.fill((10, 12, 18))
    for row in range(blocks_high):
        cell_y = top_cell + row
        for column in range(blocks_wide):
            cell_x = left_cell + column
            rect = pygame.Rect(column * pixels_per_block, row * pixels_per_block,
                               pixels_per_block, pixels_per_block)
            if visible.get((cell_x, cell_y), 1):
                color = wall_color_at((cell_x + 0.5) * TILE_SIZE,
                                      (cell_y + 0.5) * TILE_SIZE)
            else:
                color = (18, 21, 27)
            map_image.fill(color, rect)
            if pixels_per_block > 1:
                pygame.draw.rect(map_image, (25, 28, 35), rect, 1)

    def map_point(world_x, world_y):
        return (int((world_x / TILE_SIZE - left_cell) * pixels_per_block),
                int((world_y / TILE_SIZE - top_cell) * pixels_per_block))

    if not args.super_resolution:
        # Mark the player's spawn position and facing direction.
        player_point = map_point(player_x, player_y)
        pygame.draw.circle(map_image, (245, 250, 255), player_point, 5)
        facing_point = (player_point[0] + 14, player_point[1])
        pygame.draw.line(map_image, (245, 250, 255), player_point, facing_point, 2)
#         spider_point = map_point(spider["x"], spider["y"])
#         pygame.draw.circle(map_image, (220, 95, 255), spider_point, 4)

    output_path = Path(filename).expanduser().resolve()
    pygame.image.save(map_image, str(output_path))
    print(f"Saved map to {output_path} (seed {WORLD_SEED})")

if args.print_map is not None:
    print_map_png(args.print_map, args.map_size)
    pygame.quit()
    raise SystemExit(0)

MUSIC_SAMPLE_RATE = 22050
MUSIC_TEMPO = 120
MUSIC_BEAT_SECONDS = 60.0 / MUSIC_TEMPO
MUSIC_BAR_SECONDS = MUSIC_BEAT_SECONDS * 4


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


def make_drum_loop():
    """Create one repeating four-beat drum bar from synthesized saw waves."""
    loop = array("f", [0.0]) * int(MUSIC_BAR_SECONDS * MUSIC_SAMPLE_RATE)
    beat = MUSIC_BEAT_SECONDS
    for beat_index in (0, 2):
        add_saw_note(loop, beat_index * beat, 0.22, 125, 0.30, 48)
    for beat_index in (1, 3):
        at = beat_index * beat
        add_saw_note(loop, at, 0.13, 205, 0.12, 150)
        add_saw_note(loop, at, 0.10, 390, 0.055, 310)
    for eighth in range(8):
        add_saw_note(loop, eighth * beat / 2, 0.035, 3600, 0.035, 2100)
    return loop


def make_music_buffer(seed):
    """Compose four evolving 16-bar sections entirely in memory."""
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
    samples_per_bar = int(MUSIC_BAR_SECONDS * MUSIC_SAMPLE_RATE)
    mix = array("f", [0.0]) * (total_bars * samples_per_bar)
    drum_loop = make_drum_loop()

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
            bar_start = global_bar * MUSIC_BAR_SECONDS
            sample_start = global_bar * samples_per_bar
            # Repeat the same compact synthesized drum bar throughout the track.
            for sample_index, sample in enumerate(drum_loop):
                mix[sample_start + sample_index] += sample

            for beat_index, degree in enumerate(bass_pattern):
                note = root + scale[degree % 7] - 12
                if degree >= 7:
                    note += 12
                add_saw_note(
                    mix, bar_start + beat_index * MUSIC_BEAT_SECONDS,
                    MUSIC_BEAT_SECONDS * 0.82, midi_frequency(note), 0.14,
                )

            for eighth in range(8):
                degree = melody_pattern[(bar % 2) * 8 + eighth]
                if degree is None:
                    continue
                note = root + scale[degree % 7] + 12
                if degree >= 7:
                    note += 12
                add_saw_note(
                    mix, bar_start + eighth * MUSIC_BEAT_SECONDS / 2,
                    MUSIC_BEAT_SECONDS * 0.43, midi_frequency(note), 0.075,
                )
        section_first_bar += bars_per_section

    pcm = array("h")
    for sample in mix:
        pcm.append(int(max(-1.0, min(1.0, sample)) * 32767))
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


def make_arcade_sfx(kind):
    """Synthesize a short, quantized arcade effect without writing a file."""
    sample_rate = MUSIC_SAMPLE_RATE
    profiles = {
        "fire": (0.19, 880.0, 125.0),
        "wall": (0.34, 150.0, 38.0),
        "enemy_hit": (0.28, 660.0, 390.0),
        "enemy_death": (0.62, 260.0, 48.0),
        "player_hit": (0.42, 340.0, 68.0),
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


if pygame.mixer.get_init():
    pygame.mixer.set_num_channels(16)
    arcade_sfx = {
        kind: make_arcade_sfx(kind)
        for kind in ("fire", "wall", "enemy_hit", "enemy_death", "player_hit")
    }
    game_over_music = make_game_over_music()
else:
    arcade_sfx = {}
    game_over_music = None


def play_sfx(kind):
    sound = arcade_sfx.get(kind)
    if sound is not None:
        sound.play()


if pygame.mixer.get_init():
    generated_music = make_music_buffer(WORLD_SEED)
    pygame.mixer.Channel(0).play(generated_music, loops=-1)


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


game_over_title = make_game_over_title()
player_damage = 0
player_hit_cooldown = 0.0
player_regen_timer = 0.0
player_hit_flash = 0.0
game_over = False
game_over_scene = None

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif not game_over and event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
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
            })

    if not running:
        break
    if game_over:
        if game_over_scene is not None:
            screen.blit(game_over_scene, (0, 0))
        screen.blit(game_over_title, (0, 0))
        pygame.display.flip()
        clock.tick(60)
        continue
            
    # wasd movement with collision detection and wall sliding
    keys = pygame.key.get_pressed()
    move_speed = 4.0 if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else 2.0
    move = 0
    if keys[pygame.K_w]:
        move += move_speed
    if keys[pygame.K_s]:
        move -= move_speed

    def is_open(x, y):
        cell_x = math.floor(x / TILE_SIZE)
        cell_y = math.floor(y / TILE_SIZE)
        return world_block(cell_x, cell_y) == 0

    if move:
        dx = math.cos(player_angle) * move
        dy = math.sin(player_angle) * move

        # Resolve the axes separately. This preserves the unobstructed
        # component when one axis hits a wall, allowing the player to glide.
        # If both axes are blocked, neither component is applied.
        if is_open(player_x + dx, player_y):
            player_x += dx
        if is_open(player_x, player_y + dy):
            player_y += dy

    strafe = 0
    if keys[pygame.K_a]:
        strafe -= move_speed
    if keys[pygame.K_d]:
        strafe += move_speed
    if strafe:
        strafe_angle = player_angle + math.pi / 2
        strafe_x = math.cos(strafe_angle) * strafe
        strafe_y = math.sin(strafe_angle) * strafe
        if is_open(player_x + strafe_x, player_y):
            player_x += strafe_x
        if is_open(player_x, player_y + strafe_y):
            player_y += strafe_y

    if keys[pygame.K_j]:
        player_angle -= 0.05
    if keys[pygame.K_k]:
        player_angle += 0.05

    # Generate a deterministic neighborhood around the player's current cell.
    visible_map = generate_visible_map(player_x, player_y, VIEW_DISTANCE_BLOCKS)
    current_hall_id = hall_at_cell(
        math.floor(player_x / TILE_SIZE), math.floor(player_y / TILE_SIZE)
    )
    if current_hall_id is not None and current_hall_id != player_hall_id:
        spawn_hall_enemies(enemies, current_hall_id)
    player_hall_id = current_hall_id

    # Move projectiles through the map and start an explosion on wall impact.
    frame_time = clock.get_time() / 1000.0
    update_enemies(enemies, player_x, player_y, frame_time)
#     update_spider(spider, frame_time)
    for projectile in projectiles[:]:
        projectile["age"] += frame_time
        if projectile["age"] >= 5.0:
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
            if not is_open(next_x, next_y):
                # Keep the blast at the last open point, just in front of the wall.
                projectile["explosion"] = 0.35
                play_sfx("wall")
                break

            # Test the projectile's world-space segment against active enemies.
            # Segment testing prevents fast shots from skipping over a sphere.
            old_x, old_y = projectile["x"], projectile["y"]
            dx, dy = next_x - old_x, next_y - old_y
            segment_length_sq = dx * dx + dy * dy
            struck_enemy = None
            impact_t = 1.0
            hit_radius = ENEMY_RADIUS + 3.0
            for enemy in enemies:
                if enemy["virtual"]:
                    continue
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
                projectile["explosion"] = 0.35
                struck_enemy["hits"] = struck_enemy.get("hits", 0) + 1
                if struck_enemy["hits"] >= 2:
                    enemies.remove(struck_enemy)
                    # The larger burst marks the enemy's destruction.
                    projectile["enemy_kill"] = True
                    play_sfx("enemy_death")
                else:
                    play_sfx("enemy_hit")
                break

            projectile["x"] = next_x
            projectile["y"] = next_y
            projectile["depth"] += step_distance

    # Enemy contact deals damage at most once per second. A brief delay after
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

    if not game_over and player_hit_cooldown <= 0.0:
        touching_enemy = False
        for enemy in enemies:
            if enemy["virtual"]:
                continue
            dx, dy = enemy["x"] - player_x, enemy["y"] - player_y
            distance = math.hypot(dx, dy)
            if distance > ENEMY_STOP_DISTANCE:
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
            player_damage += 1
            player_hit_cooldown = 1.0
            player_regen_timer = 0.0
            player_hit_flash = 0.38
            play_sfx("player_hit")
            if player_damage >= 10:
                game_over = True
                if pygame.mixer.get_init() and game_over_music is not None:
                    pygame.mixer.Channel(0).stop()
                    pygame.mixer.Channel(0).play(game_over_music, loops=-1)

    screen.fill((10, 10, 10))  # Ultra-dark background for wireframe neon contrast

    # Raycasting Loop
    start_angle = player_angle - HALF_FOV
    wall_depths = [float("inf")] * NUM_RAYS
    max_ray_depth = VIEW_DISTANCE_BLOCKS * TILE_SIZE
    for ray in range(NUM_RAYS):
        ray_angle = start_angle + ray * STEP_ANGLE
        sin_a = math.sin(ray_angle)
        cos_a = math.cos(ray_angle)
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
            if (map_x, map_y) not in visible_map:
                break

            wall_type = visible_map[(map_x, map_y)]
            if wall_type == 0:
                continue

            hit_x = player_x + cos_a * depth
            hit_y = player_y + sin_a * depth
            corrected_depth = depth * math.cos(ray_angle - player_angle)
            # When the player is exactly on a grid boundary, a backwards ray
            # can hit the neighboring wall at depth zero. Treat it as an
            # immediate wall so projection stays finite and fills the view.
            corrected_depth = max(corrected_depth, 1e-6)
            wall_depths[ray] = corrected_depth
            wall_height = min(HEIGHT, int((TILE_SIZE / corrected_depth) * DIST_PLANE))

            # DDA gives the exact face crossed, so texture coordinates stay
            # tied to the corresponding world-space wall axis.
            wall_coordinate = hit_y if hit_side == "x" else hit_x
            stripe_period = TILE_SIZE / 8
            stripe_width = stripe_period * 0.25
            draw_stripe = (wall_coordinate % stripe_period) < stripe_width

            top_y = (HEIGHT / 2) - (wall_height / 2)
            bottom_y = (HEIGHT / 2) + (wall_height / 2)

            if draw_stripe:
                wall_color = wall_color_at(hit_x, hit_y)
                if hit_side == "x":
                    face_x, face_y = -step_x, 0
                else:
                    face_x, face_y = 0, -step_y

                reflected_light = 0.0
                for source in projectiles:
                    light_dx = source["x"] - hit_x
                    light_dy = source["y"] - hit_y
                    light_distance = math.hypot(light_dx, light_dy)
                    if light_distance <= 0:
                        continue
                    facing = max(0.0, (face_x * light_dx + face_y * light_dy) / light_distance)
                    falloff = max(0.0, 1.0 - light_distance / 180.0) ** 2
                    blast_boost = 1.0
                    if source["explosion"] > 0:
                        blast_boost = 1.4 + 0.5 * (1.0 - source["explosion"] / 0.35)
                    reflected_light += facing * falloff * blast_boost * 0.8
                if reflected_light > 0:
                    reflected_light += random.uniform(-0.12, 0.12)
                reflected_light = max(0.0, min(0.82, reflected_light))
                plasma_tint = (205, 165, 255)
                wall_color = tuple(
                    int(base * (1.0 - reflected_light) + tint * reflected_light)
                    for base, tint in zip(wall_color, plasma_tint)
                )
                pygame.draw.line(screen, wall_color, (ray, top_y), (ray, bottom_y), 1)
            break

    # Draw sprites after walls, back to front. The wall depth buffer clips each
    # sprite against the maze, and painter ordering makes nearer spheres cover
    # farther spheres where their screen shapes overlap.
    visible_enemies = [enemy for enemy in enemies if not enemy["virtual"]]
    visible_enemies.sort(
        key=lambda enemy: (enemy["x"] - player_x) * math.cos(player_angle)
        + (enemy["y"] - player_y) * math.sin(player_angle),
        reverse=True,
    )
    for enemy in visible_enemies:
        draw_enemy_floor_glow(
            screen, enemy, wall_depths, player_x, player_y, player_angle
        )
    for enemy in visible_enemies:
        draw_enemy_sphere(screen, enemy, wall_depths, player_x, player_y, player_angle)

    # Spider rendering is temporarily disabled.
#     draw_spider(screen, spider, wall_depths, player_x, player_y, player_angle)

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
        screen_x = WIDTH / 2 + math.tan(relative) * DIST_PLANE
        floor_y = HEIGHT / 2 + (TILE_SIZE / 2) * DIST_PLANE / depth
        glow_strength = 0.9
        if projectile["explosion"] > 0:
            glow_strength = 1.4 + 0.7 * (1.0 - projectile["explosion"] / 0.35)
        draw_floor_reflection(screen, screen_x, floor_y, depth, glow_strength, wall_depths)

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
        screen_x = WIDTH / 2 + math.tan(relative_angle) * DIST_PLANE
        center_y = HEIGHT / 2
        if projectile["explosion"] > 0:
            progress = 1.0 - projectile["explosion"] / 0.35
            radius_world = 3.0 + progress * (42.0 if projectile.get("enemy_kill") else 18.0)
        else:
            radius_world = 3.0
        radius = max(2, int(radius_world * DIST_PLANE / depth))
        diameter = max(2, radius * 2)
        energy_sprite = pygame.transform.smoothscale(ENERGY_TEXTURE, (diameter, diameter))
        left = max(0, int(screen_x) - radius)
        right = min(WIDTH - 1, int(screen_x) + radius)
        for x in range(left, right + 1):
            if depth >= wall_depths[x]:
                continue
            source_x = x - (int(screen_x) - radius)
            if 0 <= source_x < diameter:
                column = energy_sprite.subsurface((source_x, 0, 1, diameter))
                screen.blit(column, (x, int(center_y) - radius))

    # Add an extra pass over visible geometry before the full-screen grain.
    # Skipping the near-black clear color keeps this pass concentrated on
    # wall lines, enemy spheres, and the other rendered light sources.
    screen_grain.fill((0, 0, 0, 0))
    damage_noise_scale = 1.0 + player_damage * 0.12
    grain_colors = ((220, 205, 255), (170, 115, 255), (255, 255, 255), (130, 70, 220))
    if player_hit_flash > 0.0:
        grain_colors = ((255, 45, 18), (255, 95, 14), (255, 175, 54), (210, 12, 24))
        damage_noise_scale = max(damage_noise_scale, 2.4)
    for _ in range(5000):
        x = random.randrange(WIDTH)
        y = random.randrange(HEIGHT)
        if max(screen.get_at((x, y))[:3]) <= 14:
            continue
        color = random.choice(grain_colors)
        alpha = min(200, int(random.randint(22, 88) * damage_noise_scale))
        pygame.draw.line(screen_grain, (*color, alpha), (x, y), (x, y))
    screen.blit(screen_grain, (0, 0))

    # Full-screen film grain using the same purple and white static palette
    # as the plasma reflections. Re-sample it each frame for a subtle shimmer.
    screen_grain.fill((0, 0, 0, 0))
    for _ in range(5000):
        x = random.randrange(WIDTH)
        y = random.randrange(HEIGHT)
        color = random.choice(grain_colors)
        alpha = min(200, int(random.randint(22, 88) * damage_noise_scale))
        pygame.draw.line(screen_grain, (*color, alpha), (x, y), (x, y))
    screen.blit(screen_grain, (0, 0))

    if game_over:
        if game_over_scene is None:
            game_over_scene = screen.copy()
        screen.blit(game_over_title, (0, 0))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
