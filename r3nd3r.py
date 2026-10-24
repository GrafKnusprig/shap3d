import pygame
import math
import random
import colorsys
import argparse
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
pygame.init()
if args.print_map is not None:
    WIDTH, HEIGHT = 1000, 1000
    screen = pygame.Surface((WIDTH, HEIGHT))
else:
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
clock = pygame.time.Clock()

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

def draw_floor_reflection(target, screen_x, floor_y, depth, strength, wall_depths):
    """Draw a soft, perspective-scaled plasma glow onto the visible floor."""
    if depth <= 1:
        return
    radius_x = max(3, min(WIDTH // 2, int(58 * DIST_PLANE / depth)))
    radius_y = max(3, min(34, int(8 * DIST_PLANE / depth)))
    glow = pygame.Surface((radius_x * 2, radius_y * 2), pygame.SRCALPHA)
    layers = (
        (1.00, 1.00, (150, 65, 255, int(16 * strength))),
        (0.72, 0.68, (190, 125, 255, int(20 * strength))),
        (0.38, 0.34, (235, 215, 255, int(24 * strength))),
    )
    for scale_x, scale_y, color in layers:
        ellipse = pygame.Rect(0, 0, max(1, int(radius_x * 2 * scale_x)), max(1, int(radius_y * 2 * scale_y)))
        ellipse.center = (radius_x, radius_y)
        pygame.draw.ellipse(glow, color, ellipse)

    # A small number of newly sampled specks gives the glow a soft TV-static
    # shimmer without maintaining or drawing a large particle field.
    for _ in range(150):
        noise_x = random.randrange(radius_x * 2)
        noise_y = random.randrange(radius_y * 2)
        nx = (noise_x - radius_x) / radius_x
        ny = (noise_y - radius_y) / radius_y
        if nx * nx + ny * ny > 1 or random.random() < 0.12:
            continue
        noise_color = random.choice(((220, 205, 255), (170, 115, 255), (255, 255, 255), (130, 70, 220)))
        alpha = random.randint(24, 88)
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

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            spawn_distance = 14.0
            projectiles.append({
                "x": player_x + math.cos(player_angle) * spawn_distance,
                "y": player_y + math.sin(player_angle) * spawn_distance,
                "angle": player_angle,
                "depth": spawn_distance,
                "explosion": 0.0,
                "age": 0.0,
                "curve_phase": random.random() * math.tau,
                "trail_particles": [],
                "trail_clock": 0.0,
            })
            
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

    # Move projectiles through the map and start an explosion on wall impact.
    frame_time = clock.get_time() / 1000.0
#     update_spider(spider, frame_time)
    for projectile in projectiles[:]:
        projectile["age"] += frame_time
        for particle in projectile["trail_particles"][:]:
            particle["life"] -= frame_time
            next_x = particle["x"] + particle["vx"] * frame_time
            next_y = particle["y"] + particle["vy"] * frame_time
            if particle["life"] <= 0 or not is_open(next_x, next_y):
                projectile["trail_particles"].remove(particle)
                continue
            particle["x"] = next_x
            particle["y"] = next_y
            # Light drag makes each mote slow down as it trails behind.
            drag = max(0.0, 1.0 - 0.8 * frame_time)
            particle["vx"] *= drag
            particle["vy"] *= drag

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
                break
            projectile["x"] = next_x
            projectile["y"] = next_y
            projectile["depth"] += step_distance
        projectile["trail_clock"] += frame_time
        while projectile["trail_clock"] >= 0.045:
            projectile["trail_clock"] -= 0.045
            # Recycle a bounded set of motes. They inherit the local curve
            # direction, but start at only 42% of the ball's flight speed.
            particle_angle = flight_angle + random.uniform(-0.18, 0.18)
            particle_speed = random.uniform(125.0, 165.0)
            projectile["trail_particles"].append({
                "x": projectile["x"], "y": projectile["y"],
                "vx": math.cos(particle_angle) * particle_speed,
                "vy": math.sin(particle_angle) * particle_speed,
                "life": random.uniform(0.45, 0.7),
            })
            projectile["trail_particles"] = projectile["trail_particles"][-16:]
    

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

    # Render the small, bounded set of drifting trail motes.
    trail_layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    for projectile in projectiles:
        for particle in projectile["trail_particles"]:
            fade = max(0.0, particle["life"] / 0.7)
            if fade <= 0:
                continue
            dx, dy = particle["x"] - player_x, particle["y"] - player_y
            trail_distance = math.hypot(dx, dy)
            trail_angle = math.atan2(dy, dx)
            trail_relative = (trail_angle - player_angle + math.pi) % (2 * math.pi) - math.pi
            trail_depth = trail_distance * math.cos(trail_relative)
            if trail_depth <= 1 or abs(trail_relative) > HALF_FOV:
                continue
            trail_screen_x = int(WIDTH / 2 + math.tan(trail_relative) * DIST_PLANE)
            if not 0 <= trail_screen_x < WIDTH or trail_depth >= wall_depths[trail_screen_x]:
                continue
            trail_radius = max(1, int(2.2 * DIST_PLANE / trail_depth))
            trail_screen_y = int(HEIGHT / 2)
            alpha = int(155 * fade)
            pygame.draw.circle(
                trail_layer, (175, 100, 255, int(alpha * 0.24)),
                (trail_screen_x, trail_screen_y), trail_radius * 2,
            )
            pygame.draw.circle(
                trail_layer, (215, 185, 255, alpha),
                (trail_screen_x, trail_screen_y), trail_radius,
            )
    screen.blit(trail_layer, (0, 0))

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
            radius_world = 3.0 + progress * 18.0
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

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
