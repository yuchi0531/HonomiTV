import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type DPlayer from 'dplayer';

import CaptureManager from '@/services/player/managers/CaptureManager';


const mocks = vi.hoisted(() => ({loadFonts: vi.fn()}));
vi.mock('@/workers/CaptureCompositorProxy', () => ({default: {loadFonts: mocks.loadFonts}}));
// ファイル名のマクロは日時に依存するため、dayjs だけは実物を使う
vi.mock('@/utils', async () => {
    const dayjsModule = await import('dayjs');
    const durationPlugin = (await import('dayjs/plugin/duration')).default;
    const utcPlugin = (await import('dayjs/plugin/utc')).default;
    const timezonePlugin = (await import('dayjs/plugin/timezone')).default;
    const dayjs = dayjsModule.default;
    dayjs.extend(durationPlugin);
    dayjs.extend(utcPlugin);
    dayjs.extend(timezonePlugin);
    dayjs.tz.setDefault('Asia/Tokyo');
    return {
        default: {time: () => 0},
        dayjs: (value?: unknown) => dayjs(value as never),
        dayjsOriginal: dayjs,
    };
});
// テストごとに差し替えられるよう、チャンネル情報を外出しにする
const channelsMock = vi.hoisted(() => ({value: {} as Record<string, unknown>}));
vi.mock('@/stores/ChannelsStore', () => ({default: () => ({
    // バリデーションを通すための最小限のチャンネル情報
    channel: {current: {
        is_radiochannel: false, id: 'gr011', name: 'テスト', service_id: 1, remocon_id: 1, program_present: null,
        ...channelsMock.value,
    }},
})}));
vi.mock('@/stores/PlayerStore', () => ({default: () => ({})}));
// テストごとに差し替えられるよう、設定の中身を外出しにする
const settingsMock = vi.hoisted(() => ({value: {} as Record<string, unknown>}));
vi.mock('@/stores/SettingsStore', () => ({default: () => ({settings: settingsMock.value})}));
vi.mock('@/services/Captures', () => ({default: {}}));
vi.mock('mpeg2toh264/yadif', () => ({Deinterlacer: vi.fn()}));

function createPlayer() {
    const container = document.createElement('div');
    container.innerHTML = '<div class="dplayer-player-restart-icon"></div>';
    return {
        container, video: {videoWidth: 1920, videoHeight: 1080},
        danmaku: {showing: true}, notice: vi.fn(),
    } as unknown as DPlayer;
}

describe('キャプチャフォントの失敗を再生から分離する', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.loadFonts.mockResolvedValue(undefined);
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        vi.spyOn(console, 'error').mockImplementation(() => {});
    });

    it.each(['Live', 'Video'] as const)('%s でフォントの失敗がプレイヤー初期化を中断しない', async (mode) => {
        mocks.loadFonts.mockRejectedValue(new TypeError('Font request blocked'));
        const player = createPlayer();
        const manager = new CaptureManager(player, mode);
        await expect(manager.init()).resolves.toBeUndefined();
        expect(player.container.querySelector('.dplayer-capture-icon')).not.toBeNull();
        expect(player.container.querySelector('.dplayer-comment-capture-icon')).not.toBeNull();
        expect(player.notice).not.toHaveBeenCalled();
        expect(console.warn).toHaveBeenCalled();
    });

    it('コメント付きキャプチャで再試行し、失敗理由と次の操作をプレイヤー内に表示する', async () => {
        mocks.loadFonts.mockRejectedValue(new TypeError('Font request blocked'));
        const player = createPlayer();
        const manager = new CaptureManager(player, 'Video');
        await manager.init();
        player.container.querySelector<HTMLElement>('.dplayer-comment-capture-icon')!.click();
        await vi.waitFor(() => expect(player.notice).toHaveBeenCalled());
        expect(mocks.loadFonts).toHaveBeenCalledTimes(2);
        expect(player.notice).toHaveBeenCalledWith(expect.stringContaining('CAPTURE_FONT_LOAD_FAILED'),
            undefined, undefined, '#FF6F6A');
        expect(player.notice).toHaveBeenCalledWith(expect.stringContaining('もう一度キャプチャしてください'),
            undefined, undefined, '#FF6F6A');
        expect(player.container.querySelector('.dplayer-capturing')).toBeNull();
    });
});

describe('キャプチャのアスペクト比補正', () => {

    // happy-dom には OffscreenCanvas が無いため、実装が使う API だけを差し替える
    class StubOffscreenCanvas {
        public readonly width: number;
        public readonly height: number;
        public readonly drawn: number[][] = [];
        constructor(width: number, height: number) {
            this.width = width;
            this.height = height;
        }
        getContext() {
            return {
                imageSmoothingEnabled: false,
                imageSmoothingQuality: 'low',
                drawImage: (...args: number[]) => { this.drawn.push(args); },
            };
        }
    }

    const createBitmap = (width: number, height: number) => ({
        width, height, close: vi.fn(),
    }) as unknown as ImageBitmap;

    let created: {width: number; height: number}[] = [];

    beforeEach(() => {
        vi.clearAllMocks();
        created = [];
        vi.stubGlobal('OffscreenCanvas', StubOffscreenCanvas);
        // createImageBitmap(OffscreenCanvas) はキャンバスの寸法を引き継ぐ
        vi.stubGlobal('createImageBitmap', vi.fn(async (source: {width: number; height: number}) => {
            created.push({width: source.width, height: source.height});
            return {width: source.width, height: source.height, close: vi.fn()} as unknown as ImageBitmap;
        }));
    });

    afterEach(() => vi.unstubAllGlobals());

    // private メソッドを直接検証する (キャプチャ全体の合成は Web Worker 側の責務)
    const fix = (manager: CaptureManager, bitmap: ImageBitmap) =>
        (manager as unknown as {fixCaptureAspectRatio: (source: ImageBitmap) => Promise<ImageBitmap>})
            .fixCaptureAspectRatio(bitmap);

    it('1440×1080 (SAR 4:3) の映像を 16:9 の 1920×1080 へ引き伸ばす', async () => {
        const manager = new CaptureManager(createPlayer(), 'Live');
        const source = createBitmap(1440, 1080);

        const fixed = await fix(manager, source);

        expect(fixed.width).toBe(1920);
        expect(fixed.height).toBe(1080);
        // 補正後の比率がちょうど 16:9 になっている
        expect(fixed.width / fixed.height).toBeCloseTo(16 / 9, 5);
        // 元のビットマップは解放される
        expect(source.close).toHaveBeenCalledOnce();
    });

    it.each([
        ['1920×1080 (既に 16:9)', 1920, 1080],
        ['1280×720', 1280, 720],
        ['854×480', 854, 480],
    ])('%s は補正しない', async (_label, width, height) => {
        const manager = new CaptureManager(createPlayer(), 'Live');
        const source = createBitmap(width, height);

        const fixed = await fix(manager, source);

        // 同じインスタンスをそのまま返し、余計なリサイズをしない
        expect(fixed).toBe(source);
        expect(source.close).not.toHaveBeenCalled();
        expect(created).toHaveLength(0);
    });

    it('4:3 の 810p (1440×810 を SAR で 16:9 にしている場合) は比率だけで判定する', async () => {
        const manager = new CaptureManager(createPlayer(), 'Live');
        // 1440×810 は既に 16:9 なので補正しない
        const source = createBitmap(1440, 810);

        expect(await fix(manager, source)).toBe(source);
    });

    it('丸め誤差程度のずれは補正しない', async () => {
        const manager = new CaptureManager(createPlayer(), 'Live');
        // 16:9 から 0.5% 程度しかずれていない画像は、毎回リサイズしない
        const source = createBitmap(1920, 1082);

        expect(await fix(manager, source)).toBe(source);
    });

    it('danmaku が未生成でもコメント付きキャプチャで TypeError にならない', async () => {
        // ネットテレビからザッピングした直後は、旧プレイヤーの danmaku が未生成のことがある
        const container = document.createElement('div');
        container.innerHTML = '<div class="dplayer-player-restart-icon"></div>';
        const notice = vi.fn();
        const player = {
            container, video: {videoWidth: 1920, videoHeight: 1080},
            // danmaku が未定義
            danmaku: undefined, notice,
        } as unknown as DPlayer;
        const manager = new CaptureManager(player, 'Live');
        await manager.init();

        // コメント付きキャプチャを要求しても例外にならず、案内が表示される
        await expect(
            (manager as unknown as {captureAndSave: (is_comment: boolean) => Promise<void>})
                .captureAndSave(true),
        ).resolves.toBeUndefined();
        expect(notice).toHaveBeenCalled();
        // コメント付きキャプチャが使えないことを案内する
        expect(notice.mock.calls[0][0]).toContain('コメント付きキャプチャを利用できません');
    });
});


describe('キャプチャのファイル名のサニタイズ', () => {

    beforeEach(() => {
        vi.clearAllMocks();
        settingsMock.value = {capture_filename_pattern: 'Capture_%event-name%'};
    });

    it('番組名の半角スラッシュとコロンを置換する', () => {
        // 番組名に半角スラッシュが含まれると、そのままではサーバーに拒否されて保存できない
        channelsMock.value = {
            network_id: 1,
            program_present: {
                source: 'Broadcast', event_id: 100, title: 'FIFA/サッカー:決勝', description: '',
                start_time: '2026-10-29T12:00:00+09:00', end_time: '2026-10-29T13:00:00+09:00',
                duration: 3600,
            },
        };

        const filename = CaptureManager.generateCaptureFilename();

        // パス区切りとして解釈される文字が残らない
        expect(filename).not.toContain('/');
        expect(filename).toBe('Capture_FIFA_サッカー_決勝');
    });

    it('使える文字はそのまま残す', () => {
        channelsMock.value = {
            network_id: 1,
            program_present: {
                source: 'Broadcast', event_id: 100, title: '通常の番組名 (第3話)', description: '',
                start_time: '2026-10-29T12:00:00+09:00', end_time: '2026-10-29T13:00:00+09:00',
                duration: 3600,
            },
        };

        expect(CaptureManager.generateCaptureFilename()).toBe('Capture_通常の番組名 (第3話)');
    });
});
