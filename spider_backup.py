"""Backup of the retired wireframe spider prototype.

The game functions below expect TILE_SIZE, HALF_FOV, DIST_PLANE, WIDTH,
HEIGHT, world_block, and world_hash to be supplied by the game module.
"""
import math
import pygame

def line_is_open(x1, y1, x2, y2):
    distance = math.hypot(x2 - x1, y2 - y1)
    steps = max(1, int(distance / 8))
    for step in range(1, steps):
        ratio = step / steps
        if world_block(
            math.floor((x1 + (x2 - x1) * ratio) / TILE_SIZE),
            math.floor((y1 + (y2 - y1) * ratio) / TILE_SIZE),
        ) != 0:
            return False
    return True


def find_spider_spawn(world_x, world_y, facing):
    """Find an open, visible maze block a few steps ahead of the player."""
    start = (math.floor(world_x / TILE_SIZE), math.floor(world_y / TILE_SIZE))
    queue = [(start, 0)]
    seen = {start}
    candidates = []
    cursor = 0
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    while cursor < len(queue):
        (cell_x, cell_y), path_length = queue[cursor]
        cursor += 1
        center_x = (cell_x + 0.5) * TILE_SIZE
        center_y = (cell_y + 0.5) * TILE_SIZE
        dx, dy = center_x - world_x, center_y - world_y
        forward = dx * math.cos(facing) + dy * math.sin(facing)
        side = -dx * math.sin(facing) + dy * math.cos(facing)
        if 2 <= path_length <= 7 and TILE_SIZE * 1.5 <= forward <= TILE_SIZE * 7:
            in_front_cone = abs(side) <= forward * math.tan(HALF_FOV) * 0.6
            if in_front_cone and line_is_open(world_x, world_y, center_x, center_y):
                score = abs(forward - TILE_SIZE * 3.5) + abs(side) * 1.5
                candidates.append((score, center_x, center_y))
        if path_length >= 7:
            continue
        for step_x, step_y in directions:
            next_cell = (cell_x + step_x, cell_y + step_y)
            if next_cell not in seen and world_block(*next_cell) == 0:
                seen.add(next_cell)
                queue.append((next_cell, path_length + 1))

    if candidates:
        _, spider_x, spider_y = min(candidates)
        return spider_x, spider_y
    # The maze is connected, so this fallback still puts the spider on-path.
    (cell_x, cell_y), _ = max(queue[1:], key=lambda item: item[1])
    return (cell_x + 0.5) * TILE_SIZE, (cell_y + 0.5) * TILE_SIZE


def choose_spider_target(spider):
    """Choose a neighboring open block, avoiding an immediate reversal."""
    cell_x = math.floor(spider["x"] / TILE_SIZE)
    cell_y = math.floor(spider["y"] / TILE_SIZE)
    current = (cell_x, cell_y)
    options = []
    for step_x, step_y in ((1, 0), (0, 1), (-1, 0), (0, -1)):
        neighbor = (cell_x + step_x, cell_y + step_y)
        if world_block(*neighbor) == 0:
            options.append(neighbor)
    forward_options = [cell for cell in options if cell != spider.get("previous_cell")]
    if forward_options:
        options = forward_options
    if not options:
        return

    pick = world_hash(cell_x + 7919, cell_y - 104729) % len(options)
    target_cell = options[pick]
    spider["previous_cell"] = current
    spider["target"] = ((target_cell[0] + 0.5) * TILE_SIZE,
                        (target_cell[1] + 0.5) * TILE_SIZE)


def update_spider(spider, delta_time):
    """Walk slowly from block center to block center through open passages."""
    remaining = 22.0 * delta_time
    while remaining > 0:
        if spider["target"] is None:
            choose_spider_target(spider)
            if spider["target"] is None:
                return
        target_x, target_y = spider["target"]
        dx, dy = target_x - spider["x"], target_y - spider["y"]
        distance = math.hypot(dx, dy)
        if distance <= remaining:
            spider["x"], spider["y"] = target_x, target_y
            spider["heading"] = math.atan2(dy, dx)
            remaining -= distance
            spider["target"] = None
        else:
            spider["heading"] = math.atan2(dy, dx)
            spider["x"] += dx / distance * remaining
            spider["y"] += dy / distance * remaining
            remaining = 0


def project_world_point(world_x, world_y, height, player_x, player_y, player_angle):
    dx, dy = world_x - player_x, world_y - player_y
    forward = dx * math.cos(player_angle) + dy * math.sin(player_angle)
    if forward <= 1:
        return None
    side = -dx * math.sin(player_angle) + dy * math.cos(player_angle)
    screen_x = WIDTH / 2 + side * DIST_PLANE / forward
    screen_y = HEIGHT / 2 + (TILE_SIZE / 2 - height) * DIST_PLANE / forward
    return screen_x, screen_y, forward


def draw_spider(target, spider, wall_depths, player_x, player_y, player_angle):
    """Draw a small neon wireframe spider with world-position gait motion."""
    body = project_world_point(spider["x"], spider["y"], 12, player_x, player_y, player_angle)
    if body is None:
        return
    screen_x, screen_y, depth = body
    column = int(screen_x)
    if not 0 <= column < WIDTH or depth >= wall_depths[column]:
        return
    if abs(screen_x - WIDTH / 2) > DIST_PLANE * math.tan(HALF_FOV):
        return

    color = (255, 90, 150)
    heading = spider["heading"]
    gait = (spider["x"] * math.cos(heading) + spider["y"] * math.sin(heading)) * 0.12
    body_scale = DIST_PLANE / depth

    # Four legs swing from a phase tied to world position, so movement drives gait.
    leg_angles = (-0.72, 0.72, math.pi - 0.72, math.pi + 0.72)
    for leg_index, base_angle in enumerate(leg_angles):
        phase = gait + leg_index * math.pi
        leg_angle = heading + base_angle + math.sin(phase) * 0.25
        foot_reach = 13 + 3 * math.cos(phase)
        foot_x = spider["x"] + math.cos(leg_angle) * foot_reach
        foot_y = spider["y"] + math.sin(leg_angle) * foot_reach
        anchor_x = spider["x"] + math.cos(leg_angle) * 3
        anchor_y = spider["y"] + math.sin(leg_angle) * 3
        anchor = project_world_point(anchor_x, anchor_y, 10, player_x, player_y, player_angle)
        foot = project_world_point(foot_x, foot_y, 0, player_x, player_y, player_angle)
        if anchor is None or foot is None:
            continue
        anchor_screen_x, anchor_screen_y, _ = anchor
        foot_x_screen, foot_y_screen, foot_depth = foot
        foot_column = int(foot_x_screen)
        if 0 <= foot_column < WIDTH and foot_depth < wall_depths[foot_column]:
            pygame.draw.line(target, color, (anchor_screen_x, anchor_screen_y),
                             (foot_x_screen, foot_y_screen), max(1, int(body_scale)))

    # The abdomen is an ellipse and the thorax/head is a circle.
    abdomen_x = spider["x"] - math.cos(heading) * 5
    abdomen_y = spider["y"] - math.sin(heading) * 5
    abdomen = project_world_point(abdomen_x, abdomen_y, 12, player_x, player_y, player_angle)
    if abdomen is not None:
        ax, ay, ad = abdomen
        aw, ah = max(3, int(14 * DIST_PLANE / ad)), max(2, int(8 * DIST_PLANE / ad))
        pygame.draw.ellipse(target, color, (int(ax - aw / 2), int(ay - ah / 2), aw, ah), max(1, int(body_scale)))
    head_x = spider["x"] + math.cos(heading) * 3
    head_y = spider["y"] + math.sin(heading) * 3
    head = project_world_point(head_x, head_y, 12, player_x, player_y, player_angle)
    if head is not None:
        hx, hy, hd = head
        pygame.draw.circle(target, color, (int(hx), int(hy)), max(2, int(3 * DIST_PLANE / hd)), max(1, int(body_scale)))




def make_spider_at_start(world_x, world_y, facing):
    """Recreate the former player-start spider state."""
    spider_x, spider_y = find_spider_spawn(world_x, world_y, facing)
    return {
        "x": spider_x,
        "y": spider_y,
        "heading": facing,
        "target": None,
        "previous_cell": None,
    }


def draw_spider_map_marker(map_image, spider, map_point):
    """Draw the former spider marker on a top-down map preview."""
    spider_point = map_point(spider["x"], spider["y"])
    pygame.draw.circle(map_image, (220, 95, 255), spider_point, 4)
