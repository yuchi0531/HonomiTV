import { mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';

import { ICapture } from '@/services/Captures';
import Captures from '@/services/Captures';
import CapturesView from '@/views/Captures.vue';


const fetchCaptures = vi.fn();
const fetchFolders = vi.fn();
const userState = vi.hoisted(() => ({
    is_logged_in: true,
    user: {id: 1, name: 'viewer', is_admin: false} as {id: number; name: string; is_admin: boolean} | null,
    fetchUser: vi.fn(async () => null),
}));

vi.mock('@/services/Captures', () => ({
    default: {
        fetchCaptures: (...args: unknown[]) => fetchCaptures(...args),
        fetchFolderCaptures: (...args: unknown[]) => fetchCaptures(...args),
        fetchFolders: (...args: unknown[]) => fetchFolders(...args),
        getCaptureImageURL: (filename: string) => `/api/captures/${filename}`,
        createFolder: vi.fn(),
        updateFolder: vi.fn(),
        deleteFolder: vi.fn(),
        deleteCapture: vi.fn(),
        addCapturesToFolder: vi.fn(),
        removeCapturesFromFolder: vi.fn(),
    },
}));
vi.mock('@/stores/UserStore', () => ({default: () => userState}));
vi.mock('@/components/HeaderBar.vue', () => ({default: {template: '<div />'}}));
vi.mock('@/components/Navigation.vue', () => ({default: {template: '<div />'}}));
vi.mock('@/components/SPHeaderBar.vue', () => ({default: {template: '<div />'}}));

const buildCapture = (filename: string): ICapture => ({
    image_width: 640,
    image_height: 360,
    filename,
    file_size: 1024,
    file_modified_at: '2026-10-17T03:00:00Z',
    mime_type: 'image/jpeg',
    capture_metadata: {
        captured_at: '2026-10-17T12:00:00+09:00',
        captured_playback_position: 10,
        network_id: null,
        service_id: null,
        event_id: null,
        title: `${filename} の番組`,
        description: '',
        start_time: '2026-10-17T12:00:00+09:00',
        end_time: '2026-10-17T12:30:00+09:00',
        duration: 1800,
        caption_text: null,
        is_caption_composited: false,
        is_comment_composited: false,
    },
});

const mountView = async (path = '/captures/') => {
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [
            {path: '/captures/', component: {template: '<div />'}},
            {path: '/captures/search', component: {template: '<div />'}},
            {path: '/captures/folders/:folder_id', component: {template: '<div />'}},
        ],
    });
    await router.push(path);
    await router.isReady();

    const wrapper = mount(CapturesView, {
        global: {
            plugins: [router, createPinia()],
            directives: {ripple: {}, ftooltip: {}},
            stubs: {
                Icon: true,
                Breadcrumbs: true,
                CaptureCard: false,
                CaptureLightbox: true,
                'v-dialog': true,
                'v-card': true,
                'v-card-title': true,
                'v-card-text': true,
                'v-card-actions': true,
                'v-btn': true,
                'v-chip': true,
                'v-select': true,
                'v-pagination': true,
                'v-list': true,
                'v-list-item': true,
                'v-list-item-title': true,
                'v-list-item-subtitle': true,
                // 選択バーは transition の中にあるため、中身が描画されるスタブにする
                'v-slide-y-reverse-transition': {template: '<div><slot /></div>'},
                'v-spacer': true,
                'v-text-field': true,
            },
        },
    });
    // onMounted の非同期処理 (ユーザー取得と一覧取得) を完了させる
    await flushPromises();
    return wrapper;
};

// Vue の更新キューを流し切る
const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('キャプチャギャラリー', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        userState.is_logged_in = true;
        userState.user = {id: 1, name: 'viewer', is_admin: false};
        fetchCaptures.mockResolvedValue({total: 0, captures: []});
        fetchFolders.mockResolvedValue({total: 0, folders: []});
    });

    it('キャプチャが無いときは空状態を表示する', async () => {
        const wrapper = await mountView();
        expect(wrapper.text()).toContain('まだキャプチャがありません。');
        // 空状態は transition の対象なので、表示クラスで判定する
        expect(wrapper.find('.captures__empty').classes()).toContain('captures__empty--show');
    });

    it('一覧を取得できない場合でも空状態のまま壊れない', async () => {
        fetchCaptures.mockResolvedValue(null);
        const wrapper = await mountView();
        expect(wrapper.findAll('.capture-card')).toHaveLength(0);
        expect(wrapper.find('.captures__empty').classes()).toContain('captures__empty--show');
    });

    it('カードのクリックで選択モードに入り、5件目は選択できない', async () => {
        const files = ['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg', 'e.jpg'];
        fetchCaptures.mockResolvedValue({total: files.length, captures: files.map(buildCapture)});
        const wrapper = await mountView();
        await flushPromises();

        const cards = wrapper.findAll('.capture-card');
        expect(cards).toHaveLength(5);

        // 選択ボタンで選択モードに入る
        await wrapper.find('.captures__selection-toggle').trigger('click');
        for (const card of cards.slice(0, 4)) {
            await card.trigger('click');
        }
        expect(wrapper.text()).toContain('4件選択中');
        // 上限に達したため、未選択のカードは操作不可になる
        expect(cards[4].classes()).toContain('capture-card--disabled');

        await cards[4].trigger('click');
        expect(wrapper.text()).toContain('4件選択中');
        expect(cards[4].classes()).not.toContain('capture-card--selected');
    });

    it('選択をすべて解除すると選択モードから抜ける', async () => {
        fetchCaptures.mockResolvedValue({total: 1, captures: [buildCapture('a.jpg')]});
        const wrapper = await mountView();
        await flushPromises();

        await wrapper.find('.captures__selection-toggle').trigger('click');
        const card = wrapper.find('.capture-card');
        await card.trigger('click');
        expect(card.classes()).toContain('capture-card--selected');

        await card.trigger('click');
        expect(wrapper.text()).not.toContain('件選択中');
    });

    it('右クリック (長押し) で選択モードに入る', async () => {
        fetchCaptures.mockResolvedValue({total: 1, captures: [buildCapture('a.jpg')]});
        const wrapper = await mountView();
        await flushPromises();

        const card = wrapper.find('.capture-card');
        await card.trigger('contextmenu');
        expect(wrapper.text()).toContain('1件選択中');
    });

    it('一般ユーザーには削除可否が伝わり、管理者には許可される', async () => {
        fetchCaptures.mockResolvedValue({total: 1, captures: [buildCapture('a.jpg')]});
        const wrapper = await mountView();
        await flushPromises();

        // CaptureLightbox はスタブのため、渡された props で権限を確認する
        expect(wrapper.findComponent({name: 'CaptureLightbox'}).props('canDelete')).toBe(false);

        userState.user = {id: 2, name: 'admin', is_admin: true};
        const adminWrapper = await mountView();
        await flushPromises();
        expect(adminWrapper.findComponent({name: 'CaptureLightbox'}).props('canDelete')).toBe(true);
    });

    it('未ログインではフォルダ一覧を取りに行かず、フォルダバーも表示しない', async () => {
        userState.is_logged_in = false;
        userState.user = null;
        fetchCaptures.mockResolvedValue({total: 0, captures: []});
        const wrapper = await mountView();

        expect(fetchFolders).not.toHaveBeenCalled();
        expect(wrapper.find('.captures__folder-chips').exists()).toBe(false);
    });

    it('検索結果ではフォルダバーを出さず、検索キーワードを見出しに出す', async () => {
        const wrapper = await mountView('/captures/search?query=%E3%83%86%E3%82%B9%E3%83%88');

        expect(wrapper.text()).toContain('「テスト」の検索結果');
        expect(wrapper.find('.captures__folder-chips').exists()).toBe(false);
        // 検索キーワードはサーバー側の検索に渡される
        expect(fetchCaptures).toHaveBeenCalledWith('desc', 1, 'テスト');
    });

    it('存在しないフォルダを開こうとした場合は全体一覧へ戻す', async () => {
        // フォルダ一覧は空なので、URL の folder_id は解決できない
        fetchFolders.mockResolvedValue({total: 0, folders: []});
        const wrapper = await mountView('/captures/folders/99');

        // フォルダ内一覧の取得 (404 になる) は呼ばず、全体一覧の取得に戻る
        expect(fetchCaptures).toHaveBeenCalledWith('desc', 1, undefined);
        expect(wrapper.vm.$route.path).toBe('/captures/');
    });

    it('サムネイル URL はサーバー API を指す', () => {
        expect(Captures.getCaptureImageURL('Capture_a.jpg', true)).toBe('/api/captures/Capture_a.jpg');
    });
});
