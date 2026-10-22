import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { describe, expect, it, vi } from 'vitest';

import Channels from '@/services/Channels';
import useChannelsStore from '@/stores/ChannelsStore';
import useSettingsStore from '@/stores/SettingsStore';
import Home from '@/views/TV/Home.vue';


vi.mock('@/components/HeaderBar.vue', () => ({default: {template: '<div />'}}));
vi.mock('@/components/Navigation.vue', () => ({default: {template: '<div />'}}));
vi.mock('@/components/SPHeaderBar.vue', () => ({default: {template: '<div />'}}));
vi.mock('swiper/vue', () => ({
    Swiper: {template: '<div><slot /></div>'},
    SwiperSlide: {template: '<div><slot /></div>'},
}));
vi.mock('@/services/Channels', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/services/Channels')>();
    return {...actual, default: {...actual.default, fetchAllChannels: vi.fn()}};
});

// happy-dom はレイアウトを計算しないため、タブの実測値だけを差し替える
// タブは固定幅で並び、コンテナ幅とは一致しない (スマホ縦だと 90px 固定)
const stubTabGeometry = (wrapper: ReturnType<typeof mount>) => {
    const buttons = wrapper.element.querySelector('.channels-tab__buttons');
    expect(buttons).not.toBeNull();
    const tab_elements = wrapper.element.querySelectorAll('.channels-tab__button');
    tab_elements.forEach((element, index) => {
        Object.defineProperty(element, 'offsetLeft', {configurable: true, value: index * 90});
        Object.defineProperty(element, 'offsetWidth', {configurable: true, value: 90});
    });
};

describe('ホームのチャンネル種別タブ ハイライト', () => {
    it('コンテナ幅ではなくタブの実測位置にハイライトを合わせる', async () => {
        // 3 タブ (ピン留め / 地デジ / BS) が並ぶ想定
        vi.mocked(Channels.fetchAllChannels).mockResolvedValue({
            GR: [{id: 'gr', display_channel_id: 'gr011', network_id: 1, service_id: 1, transport_stream_id: 1,
                remocon_id: 1, channel_number: '011', type: 'GR', name: 'テスト', jikkyo_force: 0,
                is_subchannel: false, is_radiochannel: false, is_watchable: true, source: 'Broadcast',
                capabilities: {live_stream: true, live_stream_session: true, data_broadcasting: true,
                    recording: true, remote_playback: false},
                terrestrial_regions: null,
                is_display: true, viewer_count: null, program_present: null, program_following: null}],
            BS: [{id: 'bs', display_channel_id: 'bs101', network_id: 2, service_id: 2, transport_stream_id: 2,
                remocon_id: 1, channel_number: 'BS101', type: 'BS', name: 'BSテスト', jikkyo_force: 0,
                is_subchannel: false, is_radiochannel: false, is_watchable: true, source: 'Broadcast',
                capabilities: {live_stream: true, live_stream_session: true, data_broadcasting: true,
                    recording: true, remote_playback: false},
                terrestrial_regions: null,
                is_display: true, viewer_count: null, program_present: null, program_following: null}],
            CS: [], CATV: [], SKY: [], BS4K: [], IPTV: [],
            source_errors: {IPTV: null},
        });

        const wrapper = mount(Home, {global: {plugins: [createPinia()]}});
        const settings = useSettingsStore();
        // ピン留めを 1 件にして、ピン留めタブを残す
        settings.settings.pinned_channel_ids = ['x'];
        await flushPromises();
        stubTabGeometry(wrapper);

        // タブ切替後、ハイライトが実測位置へ移動する
        const store = useChannelsStore();
        await store.update(true);
        await flushPromises();

        const vm = wrapper.vm as unknown as {
            active_tab_index: number;
            tab_highlight_metrics: {left: number; width: number};
            updateTabHighlightMetrics: () => void;
        };
        vm.active_tab_index = 1;
        vm.updateTabHighlightMetrics();

        // 2 番目のタブは左端 90px、幅 90px
        expect(vm.tab_highlight_metrics.left).toBe(90);
        expect(vm.tab_highlight_metrics.width).toBe(90);
        // コンテナ幅をタブ数で割った値 (例: 375/3=125) とは異なる
        expect(vm.tab_highlight_metrics.width).not.toBe(Math.round(375 / 3));

        wrapper.unmount();
        vi.restoreAllMocks();
    });

    it('ピン留めがある状態でも地デジタブを開く', async () => {
        // タブ順は ピン留め -> 地デジ -> BS になるため、インデックス 1 は BS になってしまう
        vi.mocked(Channels.fetchAllChannels).mockResolvedValue({
            GR: [{id: 'gr', display_channel_id: 'gr011', network_id: 1, service_id: 1, transport_stream_id: 1,
                remocon_id: 1, channel_number: '011', type: 'GR', name: 'テスト', jikkyo_force: 0,
                is_subchannel: false, is_radiochannel: false, is_watchable: true, source: 'Broadcast',
                capabilities: {live_stream: true, live_stream_session: true, data_broadcasting: true,
                    recording: true, remote_playback: false},
                terrestrial_regions: null,
                is_display: true, viewer_count: null, program_present: null, program_following: null}],
            BS: [{id: 'bs', display_channel_id: 'bs101', network_id: 2, service_id: 2, transport_stream_id: 2,
                remocon_id: 1, channel_number: 'BS101', type: 'BS', name: 'BSテスト', jikkyo_force: 0,
                is_subchannel: false, is_radiochannel: false, is_watchable: true, source: 'Broadcast',
                capabilities: {live_stream: true, live_stream_session: true, data_broadcasting: true,
                    recording: true, remote_playback: false},
                terrestrial_regions: null,
                is_display: true, viewer_count: null, program_present: null, program_following: null}],
            CS: [], CATV: [], SKY: [], BS4K: [], IPTV: [],
            source_errors: {IPTV: null},
        });

        const wrapper = mount(Home, {global: {plugins: [createPinia()]}});
        const settings = useSettingsStore();
        // ピン留めを 1 件にしてピン留めタブを残す
        settings.settings.pinned_channel_ids = ['x'];
        await flushPromises();
        await useChannelsStore().update(true);
        await flushPromises();

        const vm = wrapper.vm as unknown as {
            active_tab_index: number;
            activateTabByChannelType: (type: string) => boolean;
            home_channels_list_with_pinned: Map<string, unknown[]>;
        };
        const tab_keys = Array.from(vm.home_channels_list_with_pinned.keys());
        // 地デジタブが存在し、名前から正しい位置を引ける
        const gb_index = tab_keys.indexOf('地デジ');
        expect(gb_index).toBeGreaterThanOrEqual(0);

        // 名前で指定すれば地デジタブが開く (インデックス 1 の BS ではない)
        expect(vm.activateTabByChannelType('地デジ')).toBe(true);
        expect(vm.active_tab_index).toBe(gb_index);

        // 地デジが 1 番目にない構成でも名前で正しく引ける
        if (gb_index !== 1) {
            expect(vm.active_tab_index).not.toBe(1);
        }

        // 存在しないタブを指定しても何も起きない
        const before = vm.active_tab_index;
        expect(vm.activateTabByChannelType('存在しないタブ')).toBe(false);
        expect(vm.active_tab_index).toBe(before);

        wrapper.unmount();
        vi.restoreAllMocks();
    });
});
