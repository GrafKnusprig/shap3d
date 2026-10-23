import pygame
import math
import random

# Initialize Pygame
pygame.init()
WIDTH, HEIGHT = 640, 480
screen = pygame.display.set_mode((WIDTH, HEIGHT))
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

# Map Configuration (0 = empty; positive values select a wall color)
MAP = [
    [1,1,1,1,1,1,1,1],
    [1,0,0,0,0,0,0,1],
    [1,0,2,1,0,3,0,1],
    [1,0,0,0,0,0,0,1],
    [1,0,1,0,1,1,0,1],
    [1,0,1,0,0,0,0,1],
    [1,0,0,0,1,0,0,1],
    [1,1,1,1,1,1,1,1],
]
WALL_COLORS = {
    1: (0, 255, 100),   # neon green
    2: (0, 190, 255),   # cyan
    3: (255, 120, 40),  # orange
}
TILE_SIZE = 64
FOV = 2 * math.pi / 3  # 120 degrees Field of View
HALF_FOV = FOV / 2
NUM_RAYS = WIDTH  # One ray per column
STEP_ANGLE = FOV / NUM_RAYS
DIST_PLANE = (WIDTH / 2) / math.tan(HALF_FOV)

# Player Parameters
player_x, player_y = 120.0, 120.0
player_angle = 0.0
projectiles = []
muzzle_flash = 0.0

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            muzzle_flash = 0.11
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
        map_x, map_y = int(x / TILE_SIZE), int(y / TILE_SIZE)
        return (0 <= map_y < len(MAP) and
                0 <= map_x < len(MAP[0]) and MAP[map_y][map_x] == 0)

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

    # Move projectiles through the map and start an explosion on wall impact.
    frame_time = clock.get_time() / 1000.0
    muzzle_flash = max(0.0, muzzle_flash - frame_time)
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
    for ray in range(NUM_RAYS):
        ray_angle = start_angle + ray * STEP_ANGLE
        
        # Simple Incremental Ray Marching (for didactic simplicity)
        sin_a = math.sin(ray_angle)
        cos_a = math.cos(ray_angle)
        
        for depth in range(1, 800):
            target_x = player_x + cos_a * depth
            target_y = player_y + sin_a * depth
            
            map_x, map_y = int(target_x / TILE_SIZE), int(target_y / TILE_SIZE)

            # A ray may leave the map before it reaches a wall.
            if not (0 <= map_y < len(MAP) and 0 <= map_x < len(MAP[0])):
                break
            
            # Hit Wall Boundary
            wall_type = MAP[map_y][map_x]
            if wall_type > 0:
                # Correct fisheye lens distortion
                corrected_depth = depth * math.cos(ray_angle - player_angle)
                wall_depths[ray] = corrected_depth
                
                # Calculate Wall Projection Height
                wall_height = min(HEIGHT, int((TILE_SIZE / corrected_depth) * DIST_PLANE))
                
                # Project a pattern defined in world space.  Unlike selecting
                # every Nth screen column, this makes both stripe widths and
                # gaps shrink with distance naturally.
                x_edge_distance = min(
                    target_x - map_x * TILE_SIZE,
                    (map_x + 1) * TILE_SIZE - target_x,
                )
                y_edge_distance = min(
                    target_y - map_y * TILE_SIZE,
                    (map_y + 1) * TILE_SIZE - target_y,
                )
                wall_coordinate = target_y if x_edge_distance < y_edge_distance else target_x
                # Keep the pattern in world space: eight vertical stripe
                # bands across each tile. Their projected screen width grows
                # as the wall gets closer, without changing stripe density.
                stripe_period = TILE_SIZE / 8
                stripe_width = stripe_period * 0.25
                stripe_phase = wall_coordinate % stripe_period
                draw_stripe = stripe_phase < stripe_width

                # Draw the Wireframe Edges (Top and Bottom Points)
                top_y = (HEIGHT / 2) - (wall_height / 2)
                bottom_y = (HEIGHT / 2) + (wall_height / 2)
                
                if draw_stripe:
                    wall_color = WALL_COLORS.get(wall_type, (255, 0, 255))
                    if x_edge_distance < y_edge_distance:
                        face_x = -1 if cos_a > 0 else 1
                        face_y = 0
                    else:
                        face_x = 0
                        face_y = -1 if sin_a > 0 else 1

                    reflected_light = 0.0
                    for source in projectiles:
                        light_dx = source["x"] - target_x
                        light_dy = source["y"] - target_y
                        light_distance = math.hypot(light_dx, light_dy)
                        if light_distance <= 0:
                            continue
                        facing = max(0.0, (face_x * light_dx + face_y * light_dy) / light_distance)
                        falloff = max(0.0, 1.0 - light_distance / 180.0) ** 2
                        blast_boost = 1.0
                        if source["explosion"] > 0:
                            blast_boost = 1.4 + 0.5 * (1.0 - source["explosion"] / 0.35)
                        reflected_light += facing * falloff * blast_boost * 0.8
                    if muzzle_flash > 0:
                        light_dx = player_x - target_x
                        light_dy = player_y - target_y
                        light_distance = math.hypot(light_dx, light_dy)
                        if light_distance > 0:
                            facing = max(0.0, (face_x * light_dx + face_y * light_dy) / light_distance)
                            falloff = max(0.0, 1.0 - light_distance / 150.0) ** 2
                            reflected_light += facing * falloff * (muzzle_flash / 0.11) * 1.8
                    if reflected_light > 0:
                        reflected_light += random.uniform(-0.12, 0.12)
                    reflected_light = min(0.82, reflected_light)
                    reflected_light = max(0.0, reflected_light)
                    plasma_tint = (205, 165, 255)
                    wall_color = tuple(
                        int(base * (1.0 - reflected_light) + tint * reflected_light)
                        for base, tint in zip(wall_color, plasma_tint)
                    )
                    pygame.draw.line(screen, wall_color, (ray, top_y), (ray, bottom_y), 1)
                break

    # Brief floor reflection at the player's feet, clipped against wall depth.
    if muzzle_flash > 0:
        strength = muzzle_flash / 0.11
        foot_glow = pygame.Surface((420, 160), pygame.SRCALPHA)
        pygame.draw.ellipse(foot_glow, (125, 55, 230, int(20 * strength)), (0, 0, 420, 160))
        pygame.draw.ellipse(foot_glow, (190, 130, 255, int(25 * strength)), (75, 25, 270, 110))
        pygame.draw.ellipse(foot_glow, (235, 215, 255, int(22 * strength)), (145, 55, 130, 65))
        glow_left, glow_top = (WIDTH - 420) // 2, HEIGHT - 160
        for x in range(glow_left, glow_left + 420):
            wall_depth = wall_depths[x]
            floor_cutoff = HEIGHT / 2
            if wall_depth != float("inf"):
                floor_cutoff += (TILE_SIZE / 2) * DIST_PLANE / wall_depth
            visible_top = max(glow_top, int(floor_cutoff), 0)
            if visible_top < HEIGHT:
                glow_column = foot_glow.subsurface((x - glow_left, visible_top - glow_top, 1, HEIGHT - visible_top))
                screen.blit(glow_column, (x, visible_top))

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
