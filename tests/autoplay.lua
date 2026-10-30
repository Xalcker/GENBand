-- Bot de pruebas de GENBand para MAME: pasa el título, elige en el menú como lo haría un jugador
-- (con el control 1), toca la canción leyendo las notas de la RAM y, en los resultados, escribe
-- resultado.txt y capturas de pantalla. Lo corre tests/run_tests.sh.
--
-- Parámetros (variables de entorno):
--   GENBAND_SYM    símbolos de la ROM (build/genband.sym, salida de nm)
--   GENBAND_OUT    carpeta donde van resultado.txt y las capturas
--   GENBAND_SONG, GENBAND_INSTR, GENBAND_DIFF   lo que se elige en el menú (números, desde 0)
--   GENBAND_OPTS   opciones (pantalla de A en el menú), como "espejo=1 velocidad=1 practica=1 inicio=0"
--                  (los valores son el número de la opción, desde 0)
--   GENBAND_MODE   perfecto (acierta todo), nada (no toca: debe perder), mitad (falla una de cada dos),
--                  sinfallo (no toca, con SIN FALLO: debe llegar al final), aire (acierta todo y además,
--                  cada 2 segundos, aprieta un carril sin nota: golpes al aire), practica (acierta todo
--                  y, cuando la práctica se repitió dos veces, sale al menú desde la pausa), record (acierta
--                  todo y escribe las iniciales BOT), leer_record (no juega: lee la tabla de récords al
--                  llegar al menú, para ver que sobrevivió a apagar la consola)

local sym_path = os.getenv("GENBAND_SYM")
local out = os.getenv("GENBAND_OUT")
local want_song = tonumber(os.getenv("GENBAND_SONG") or "0")
local want_instr = tonumber(os.getenv("GENBAND_INSTR") or "0")
local want_diff = tonumber(os.getenv("GENBAND_DIFF") or "3")
local mode = os.getenv("GENBAND_MODE") or "perfecto"
local opts = {}
for k, v in (os.getenv("GENBAND_OPTS") or ""):gmatch("(%w+)=(%d+)") do opts[k] = tonumber(v) end
local OPTION_ORDER = { "espejo", "velocidad", "caida", "practica", "inicio", "efecto" }

local SCREEN_TITLE, SCREEN_MENU, SCREEN_PLAY, SCREEN_RESULTS, SCREEN_OPTIONS, SCREEN_INITIALS = 1, 2, 3, 4, 5, 6 -- (0: arrancando)
local GEM_SLOTS, GEM_SIZE = 64, 8
local SUSTAIN = 0x40
local TIMEOUT = 60 * 60 * 8 -- cuadros: ninguna canción dura tanto

local sym = {}
for line in io.lines(sym_path) do
    local addr, _, name = line:match("^(%x+) (%a) (%S+)$")
    if addr then sym[name] = tonumber(addr, 16) & 0xFFFFFF end
end
for _, name in ipairs({ "current_screen", "sel", "result", "now", "gems", "gem_head", "gem_tail" }) do
    assert(sym[name], "falta el símbolo " .. name .. " en " .. sym_path)
end

local mem = manager.machine.devices[":maincpu"].spaces["program"]
local pad = manager.machine.ioport.ports[":ctrl1:mdpad:PAD"]
local field = {
    up = pad.fields["P1 Up"], down = pad.fields["P1 Down"], left = pad.fields["P1 Left"],
    right = pad.fields["P1 Right"], a = pad.fields["P1 A"], b = pad.fields["P1 B"], c = pad.fields["P1 C"],
    start = pad.fields["P1 Start"],
}
-- Carriles con el control de 3 botones: ←, ↓, →, B, C
local lane_field = { field.left, field.down, field.right, field.b, field.c }

local function screen() return mem:read_u32(sym.current_screen) end

local frame = 0
local log = io.open(out .. "/bot.log", "w")
local function note(text) log:write(string.format("%6d %s\n", frame, text)) log:flush() end

local function snapshot(name)
    manager.machine.video:snapshot()
    note("captura " .. name)
end

-- Una cola de pulsaciones para los menús: {campo, cuadros presionado}
local queue = {}
local held_until = {}
local function tap(f) table.insert(queue, f) end

local function menu_plan()
    -- El menú arranca en CANCION; se baja a cada renglón y se cambia el valor con ←/→
    local song = mem:read_u16(sym.sel)
    local instr = mem:read_u16(sym.sel + 2)
    local diff = mem:read_u16(sym.sel + 4)
    local no_fail = mem:read_u8(sym.sel + 6)
    for _ = 1, (want_song - song) % 64 do tap(field.right) end
    tap(field.down)
    for _ = 1, (want_instr - instr) % 3 do tap(field.right) end
    tap(field.down)
    for _ = 1, (want_diff - diff) % 4 do tap(field.right) end
    tap(field.down)
    if (mode == "sinfallo") ~= (no_fail ~= 0) then tap(field.right) end
    if next(opts) then
        -- Opciones: A las abre; cada renglón empieza en su valor normal (0)
        tap(field.a)
        table.insert(queue, { screen = SCREEN_OPTIONS })
        for _, name in ipairs(OPTION_ORDER) do
            for _ = 1, (opts[name] or 0) do tap(field.right) end
            tap(field.down)
        end
    end
    tap(field.start)
end

local state = "titulo"
local wait = 0
local lane_release = { nil, nil, nil, nil, nil }
local lane_gem = { nil, nil, nil, nil, nil } -- dirección de la nota sostenida cuyo fin aún no se leía
local skip_toggle = false
local shots = {}
local missed_on_purpose = 0

local function release_all()
    for _, f in pairs(field) do f:set_value(0) end
end

local function play()
    local now = mem:read_u16(sym.now)
    local head = mem:read_u16(sym.gem_head)
    local tail = mem:read_u16(sym.gem_tail)
    -- Una cola larga: su fin se lee del chart cuando entra a la pantalla
    for lane = 1, 5 do
        if lane_gem[lane] then
            local gend = mem:read_u16(lane_gem[lane] + 2)
            if gend > 0 then
                lane_release[lane] = gend
                lane_gem[lane] = nil
            end
        end
    end
    -- Soltar lo que ya toca soltar
    for lane = 1, 5 do
        if lane_release[lane] and now >= lane_release[lane] then
            lane_field[lane]:set_value(0)
            lane_release[lane] = nil
        end
    end
    if mode == "nada" or mode == "sinfallo" then return end
    -- Golpe al aire: el carril naranja, si no tiene una nota cerca
    if mode == "aire" and now % 120 == 60 and not lane_release[5] then
        local free = true
        local m = head
        while m ~= tail do
            local b = sym.gems + (m % GEM_SLOTS) * GEM_SIZE
            local f = mem:read_u16(b)
            if f > now + 10 then break end
            if mem:read_u8(b + 4) & 0x10 ~= 0 and f + 10 >= now then free = false end
            m = (m + 1) & 0xFFFF
        end
        if free then
            lane_field[5]:set_value(1)
            lane_release[5] = now + 2
            air_hits = (air_hits or 0) + 1
            if air_hits == 3 then shot_at = frame + 4 end
        end
    end
    -- Tocar las notas de este cuadro (el juego las juzga en el siguiente ciclo, con este mismo `now`)
    local n = head
    while n ~= tail do
        local base = sym.gems + (n % GEM_SLOTS) * GEM_SIZE
        local gframe = mem:read_u16(base)
        if gframe > now + 2 then break end
        local gend = mem:read_u16(base + 2)
        local mask = mem:read_u8(base + 4)
        local flags = mem:read_u8(base + 5)
        local done = mem:read_u8(base + 6) | mem:read_u8(base + 7)
        local open = mask & ~done
        if open ~= 0 and gframe == now then
            skip_toggle = not skip_toggle
            if mode == "mitad" and skip_toggle then
                missed_on_purpose = missed_on_purpose + 1
            else
                for lane = 1, 5 do
                    if open & (1 << (lane - 1)) ~= 0 and not lane_release[lane] then
                        lane_field[lane]:set_value(1)
                        local until_frame = now + 3
                        if flags & SUSTAIN ~= 0 and gend > 0 then until_frame = math.max(until_frame, gend) end
                        if flags & SUSTAIN ~= 0 and gend == 0 then
                            until_frame = now + 6000
                            lane_gem[lane] = base
                        end
                        lane_release[lane] = until_frame
                    end
                end
            end
        end
        n = (n + 1) & 0xFFFF
    end
end

-- El récord de la canción elegida en la tabla de la RAM (records.c): puntaje e iniciales, o nil
local REC_SIZE_RAM = 12 -- sizeof(Record) en el 68000: id(2) clave(1) relleno(1) puntaje(4) iniciales(3) estrellas(1)
local function find_record()
    local hash = nil
    -- El hash de la canción: Song.hash de song_list[GENBAND_SONG]
    local song = mem:read_u32(sym.song_list + want_song * 4) & 0xFFFFFF
    hash = mem:read_u16(song + 4 * 3 + 2 * 3)
    for i = 0, 249 do
        local b = sym.rec_table + i * REC_SIZE_RAM
        if mem:read_u8(b + 2) == want_instr * 4 + want_diff and mem:read_u16(b) == hash then
            local ini = string.char(mem:read_u8(b + 8), mem:read_u8(b + 9), mem:read_u8(b + 10))
            return mem:read_u32(b + 4), ini
        end
    end
    return nil
end

local function write_result()
    local r = sym.result
    local f = io.open(out .. "/resultado.txt", "w")
    f:write(string.format("modo=%s\ncancion=%d\ninstrumento=%d\ndificultad=%d\n", mode, want_song, want_instr, want_diff))
    f:write(string.format("puntaje=%d\nperfecto=%d\nnotas=%d\ntotal=%d\ncombo_max=%d\nprecision=%d\nestrellas=%d\nfallo=%d\n",
        mem:read_u32(r), mem:read_u32(r + 4), mem:read_u16(r + 8), mem:read_u16(r + 10), mem:read_u16(r + 12),
        mem:read_u16(r + 14), mem:read_u16(r + 16), mem:read_u8(r + 18)))
    f:write(string.format("cuadros=%d\nnuevo_record=%d\n", frame, mem:read_u8(r + 19)))
    f:close()
end

emu.register_frame_done(function()
    frame = frame + 1
    if frame > TIMEOUT then
        note("se acabó el tiempo")
        manager.machine:exit()
        return
    end

    -- Pulsaciones de menú: cada una dura 2 cuadros y deja 4 libres
    if wait > 0 then
        wait = wait - 1
        if wait == 4 then release_all() end
        return
    end

    local s = screen()
    if frame % 600 == 0 then
        note(string.format("pantalla %d, cuadro de la canción %d", s, mem:read_u16(sym.now)))
    end
    if state == "titulo" then
        if s == SCREEN_TITLE then
            title_frames = (title_frames or 0) + 1
        end
        if title_frames and title_frames > 60 then
            snapshot("titulo")
            tap(field.start)
            state = "al_menu"
        end
    elseif state == "al_menu" then
        if s == SCREEN_MENU and mode == "leer_record" then
            local score, ini = find_record()
            local f = io.open(out .. "/resultado.txt", "w")
            f:write(string.format("modo=leer_record\nrecord=%d\niniciales=%s\npuntaje=0\nnotas=0\ntotal=0\ncombo_max=0\nestrellas=0\nfallo=0\n",
                score or 0, ini or "---"))
            f:close()
            snapshot("menu con record")
            state = "fin"
            wait = 3
            return
        end
        if s == SCREEN_MENU then
            state = "menu"
            wait = 30
            return
        end
    elseif state == "menu" then
        if #queue == 0 then
            menu_plan()
            state = "eligiendo"
        end
    elseif state == "eligiendo" then
        if #queue == 1 then snapshot("menu") end
        if #queue == 0 and s == SCREEN_PLAY then
            state = "jugando"
            note("juego: modo " .. mode)

        end
    elseif state == "jugando" then
        if s == SCREEN_PLAY then
            play()
            local now = mem:read_u16(sym.now)
            if mode == "practica" or mode == "marcas" then
                if last_now and now + 30 < last_now then
                    -- (el primer reinicio tras marcar es el de la marca; el siguiente, el fin del bucle)
                    if marked and restarted_after_mark and not loop_end then loop_end = last_now end
                    if marked then restarted_after_mark = true end
                    loops = (loops or 0) + 1
                    loop_frame = frame
                    note("la práctica volvió a empezar")
                end
                last_now = now
                -- Marcas: en la primera vuelta, a los 6 s, pausa y B (el bucle termina ahí)
                if mode == "marcas" and (loops or 0) == 1 and not marked and frame > loop_frame + 360 and #queue == 0 then
                    marked = now
                    note("marca de fin en el cuadro " .. now)
                    release_all()
                    tap(field.start)
                    tap(field.b)
                end
                -- (no justo al reiniciar: mientras se adelanta la música el juego no lee el control)
                if (loops or 0) >= (mode == "marcas" and 3 or 2) and frame > loop_frame + 120 and #queue == 0 and not leaving then
                    leaving = true
                    note("a la pausa y al menú, en el cuadro " .. now)
                    release_all()
                    tap(field.start)
                    tap(field.c)
                end
            end
            if shot_at and frame == shot_at then snapshot("aire") end
            if now == 1200 and not shots.juego then
                shots.juego = true
                snapshot("juego")
            end
        elseif s == SCREEN_RESULTS then
            release_all()
            state = "resultados"
            wait = 60
            return
        elseif s == SCREEN_MENU and (mode == "practica" or mode == "marcas") then
            local f = io.open(out .. "/resultado.txt", "w")
            f:write(string.format("modo=%s\nvueltas=%d\nmarca=%d\nfin_bucle=%d\npuntaje=0\nnotas=0\ntotal=0\ncombo_max=0\nestrellas=0\nfallo=0\n",
                mode, loops or 0, marked or 0, loop_end or 0))
            f:close()
            note("de vuelta en el menú tras " .. (loops or 0) .. " vueltas")
            state = "fin"
            wait = 3
            return
        end
    elseif state == "resultados" then
        snapshot("resultados")
        write_result()
        if mode == "record" then
            -- Iniciales: de las que traiga (AAA la primera vez) a BOT
            tap(field.start)
            table.insert(queue, { screen = SCREEN_INITIALS })
            for _ = 1, 1 do tap(field.up) end
            tap(field.right)
            for _ = 1, 14 do tap(field.up) end
            tap(field.right)
            for _ = 1, 19 do tap(field.up) end
            tap(field.start)
            table.insert(queue, { screen = SCREEN_MENU })
            state = "iniciales"
            return
        end
        note("fin (notas falladas a propósito: " .. missed_on_purpose .. ", golpes al aire: " .. (air_hits or 0) .. ")")
        state = "fin"
        wait = 3
        return
    elseif state == "iniciales" then
        if #queue == 0 then
            local score, ini = find_record()
            local f = io.open(out .. "/resultado.txt", "a")
            f:write(string.format("record=%d\niniciales=%s\n", score or 0, ini or "---"))
            f:close()
            snapshot("menu con record")
            note("récord guardado: " .. (score or 0) .. " " .. (ini or "---"))
            state = "fin"
            wait = 3
            return
        end
    elseif state == "fin" then
        manager.machine:exit()
        return
    end

    if #queue > 0 then
        local f = queue[1]
        if type(f) == "table" and f.screen then
            -- Esperar a que la pantalla esté lista (y unos cuadros más) antes de seguir
            if s == f.screen then
                table.remove(queue, 1)
                wait = 20
            end
            return
        end
        table.remove(queue, 1)
        f:set_value(1)
        wait = 6
    end
end)
