-- Bot de pruebas de GENBand para MAME: pasa el título, elige en el menú como lo haría un jugador
-- (con el control 1), toca la canción leyendo las notas de la RAM y, en los resultados, escribe
-- resultado.txt y capturas de pantalla. Lo corre tests/run_tests.sh.
--
-- Parámetros (variables de entorno):
--   GENBAND_SYM    símbolos de la ROM (build/genband.sym, salida de nm)
--   GENBAND_OUT    carpeta donde van resultado.txt y las capturas
--   GENBAND_SONG, GENBAND_INSTR, GENBAND_DIFF   lo que se elige en el menú (números, desde 0)
--   GENBAND_MODE   perfecto (acierta todo), nada (no toca: debe perder), mitad (falla una de cada dos),
--                  sinfallo (no toca, con SIN FALLO: debe llegar al final)

local sym_path = os.getenv("GENBAND_SYM")
local out = os.getenv("GENBAND_OUT")
local want_song = tonumber(os.getenv("GENBAND_SONG") or "0")
local want_instr = tonumber(os.getenv("GENBAND_INSTR") or "0")
local want_diff = tonumber(os.getenv("GENBAND_DIFF") or "3")
local mode = os.getenv("GENBAND_MODE") or "perfecto"

local SCREEN_TITLE, SCREEN_MENU, SCREEN_PLAY, SCREEN_RESULTS = 1, 2, 3, 4 -- (0: arrancando)
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
    tap(field.start)
end

local state = "titulo"
local wait = 0
local lane_release = { nil, nil, nil, nil, nil }
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
    -- Soltar lo que ya toca soltar
    for lane = 1, 5 do
        if lane_release[lane] and now >= lane_release[lane] then
            lane_field[lane]:set_value(0)
            lane_release[lane] = nil
        end
    end
    if mode == "nada" or mode == "sinfallo" then return end
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
                        if flags & SUSTAIN ~= 0 and gend == 0 then until_frame = now + 600 end
                        lane_release[lane] = until_frame
                    end
                end
            end
        end
        n = (n + 1) & 0xFFFF
    end
end

local function write_result()
    local r = sym.result
    local f = io.open(out .. "/resultado.txt", "w")
    f:write(string.format("modo=%s\ncancion=%d\ninstrumento=%d\ndificultad=%d\n", mode, want_song, want_instr, want_diff))
    f:write(string.format("puntaje=%d\nperfecto=%d\nnotas=%d\ntotal=%d\ncombo_max=%d\nprecision=%d\nestrellas=%d\nfallo=%d\n",
        mem:read_u32(r), mem:read_u32(r + 4), mem:read_u16(r + 8), mem:read_u16(r + 10), mem:read_u16(r + 12),
        mem:read_u16(r + 14), mem:read_u16(r + 16), mem:read_u8(r + 18)))
    f:write(string.format("cuadros=%d\n", frame))
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
            if now == 1200 and not shots.juego then
                shots.juego = true
                snapshot("juego")
            end
        elseif s == SCREEN_RESULTS then
            release_all()
            state = "resultados"
            wait = 60
            return
        end
    elseif state == "resultados" then
        snapshot("resultados")
        write_result()
        note("fin (notas falladas a propósito: " .. missed_on_purpose .. ")")
        state = "fin"
        wait = 3
        return
    elseif state == "fin" then
        manager.machine:exit()
        return
    end

    if #queue > 0 then
        local f = table.remove(queue, 1)
        f:set_value(1)
        wait = 6
    end
end)
