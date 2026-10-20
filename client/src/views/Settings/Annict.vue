<template>
    <!-- ベース画面の中にそれぞれの設定画面で異なる部分を記述する -->
    <SettingsBase>
        <h2 class="settings__heading">
            <a v-ripple class="settings__back-button" @click="$router.back()">
                <Icon icon="fluent:chevron-left-12-filled" width="27px" />
            </a>
            <Icon icon="fluent:movies-and-tv-20-filled" width="23px" />
            <span class="ml-2">Annict 連携</span>
        </h2>
        <div class="settings__description">
            <a class="link" href="https://annict.com/" target="_blank">Annict</a> の個人用アクセストークンを使ってアカウントを連携します。<br>
            視聴した番組を Annict の視聴記録へ反映する機能で利用されます。Bangumi 連携とは独立しており、両方を同時に使えます。<br>
        </div>
        <div class="settings__content" :class="{'settings__content--loading': isLoading}">
            <div class="annict-account annict-account--anonymous"
                v-if="isLoading === false && (userStore.user === null || userStore.user.annict_user_id === null)">
                <div class="annict-account-wrapper">
                    <Icon class="flex-shrink-0" icon="fluent:movies-and-tv-20-filled" width="45px" />
                    <div class="annict-account__info ml-4">
                        <div class="annict-account__info-name">Annict アカウントと連携していません</div>
                        <span class="annict-account__info-description">
                            KonomiTV アカウントへのログインと、Annict の個人用アクセストークンが必要です。
                        </span>
                    </div>
                </div>
                <v-btn class="annict-account__button ml-auto" color="secondary" width="130" height="56" variant="flat"
                    @click="openAccountLinkDialog()">
                    <Icon icon="fluent:plug-connected-20-filled" class="mr-2" height="26" />連携する
                </v-btn>
            </div>
            <div class="annict-account"
                v-if="isLoading === false && userStore.user !== null && userStore.user.annict_user_id !== null">
                <div class="annict-account-wrapper">
                    <img class="annict-account__icon" :src="userStore.user.annict_user_avatar_url ?? ''">
                    <div class="annict-account__info">
                        <div class="annict-account__info-name">{{userStore.user.annict_user_nickname}} と連携しています</div>
                        <span class="annict-account__info-description">
                            <a class="link" :href="`https://annict.com/@${userStore.user.annict_user_name}`" target="_blank">
                                @{{userStore.user.annict_user_name}}
                            </a>
                            <span class="ml-2">User ID: {{userStore.user.annict_user_id}}</span>
                        </span>
                    </div>
                </div>
                <div class="annict-account__actions ml-auto">
                    <v-btn color="secondary" variant="outlined" height="42" @click="openAccountLinkDialog()">再連携</v-btn>
                    <v-btn color="secondary" variant="flat" height="42" @click="logoutAnnictAccount()">
                        <Icon icon="fluent:plug-disconnected-20-filled" class="mr-2" height="22" />連携解除
                    </v-btn>
                </div>
            </div>
            <div class="settings__item settings__item--switch mt-6">
                <label class="settings__item-heading" for="annict_auto_record_playback">視聴記録の自動投稿</label>
                <label class="settings__item-label" for="annict_auto_record_playback">
                    Annict の視聴記録 (record) は<b>公開の視聴ログ</b>です。オンにすると、視聴完了したエピソードが Annict 上に記録されます。<br>
                    既定ではオフになっています。オフの間は Annict へ一切書き込みません。<br>
                    同じエピソードは一度しか記録されません。連続放送 (1 本の録画に複数話が入っているもの) は、誤った話へ記録しないため対象外です。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="annict_auto_record_playback" hide-details
                    :disabled="userStore.user === null || userStore.user.annict_user_id === null"
                    :loading="isUpdatingAutoRecord"
                    :model-value="userStore.user !== null && userStore.user.annict_auto_record_playback"
                    @update:model-value="updateAutoRecordSetting">
                </v-switch>
            </div>
            <div class="settings__item">
                <div class="settings__item-heading">個人用アクセストークンについて</div>
                <div class="settings__item-label">
                    入力されたトークンは KonomiTV サーバーのデータベースへ暗号化して保存され、クライアントには返されません。<br>
                    Annict のトークンは自動更新されないため、失効した場合は再連携してください。<br>
                    書き込みには「読み込み + 書き込み」のスコープを持つトークンが必要です (読み込み専用では視聴記録を投稿できません)。<br>
                </div>
                <v-btn class="settings__save-button mt-4" variant="flat" href="https://annict.com/settings/apps" target="_blank">
                    <Icon icon="fluent:key-20-filled" height="21px" />
                    <span class="ml-2">Annict で個人用アクセストークンを作成</span>
                </v-btn>
            </div>

            <v-divider class="mt-6"></v-divider>
            <div class="settings__item">
                <div class="settings__item-heading">シリーズを Annict 作品へ手動で紐づける</div>
                <div class="settings__item-label">
                    自動照合で Annict 作品に紐づかなかったシリーズを、手動で紐づけられます。<br>
                    タイトルの表記が違う作品や、Annict でのタイトルが異なる作品はこちらから指定してください。<br>
                </div>
                <v-btn class="settings__save-button mt-4" variant="flat" :loading="is_loading_unlinked"
                    @click="openManualLinkDialog()">
                    <Icon icon="fluent:link-20-filled" height="21px" />
                    <span class="ml-2">未紐づけのシリーズを開く</span>
                </v-btn>
            </div>
        </div>

        <!-- 手動紐づけダイアログ -->
        <v-dialog v-model="manual_link_dialog" max-width="720" scrollable>
            <v-card>
                <v-card-title>シリーズを Annict 作品へ紐づける</v-card-title>
                <v-card-text>
                    <div v-if="unlinked_series.length === 0" class="text-text-darken-1">
                        未紐づけのシリーズはありません。
                    </div>
                    <template v-else>
                        <div class="settings__item">
                            <div class="settings__item-heading">未紐づけのシリーズ</div>
                            <v-select class="settings__item-form" color="primary" variant="outlined" hide-details
                                item-title="title" item-value="id" :items="unlinked_series"
                                v-model="selected_series_id" @update:model-value="onSeriesSelected">
                            </v-select>
                        </div>
                        <div class="settings__item mt-4">
                            <div class="settings__item-heading">Annict の作品を検索</div>
                            <div class="d-flex align-center">
                                <v-text-field class="settings__item-form" color="primary" variant="outlined" hide-details
                                    placeholder="作品タイトル" v-model="work_search_query"
                                    @keydown.enter="searchWorks()">
                                </v-text-field>
                                <v-btn class="ml-3" variant="flat" color="secondary" height="48"
                                    :loading="is_searching_works" @click="searchWorks()">
                                    検索
                                </v-btn>
                            </div>
                        </div>
                        <div class="settings__item mt-4" v-if="work_candidates.length > 0">
                            <div class="settings__item-heading">検索結果から選択</div>
                            <v-list density="compact">
                                <v-list-item v-for="work in work_candidates" :key="work.id"
                                    :active="selected_work_id === work.id"
                                    @click="selected_work_id = work.id">
                                    <v-list-item-title>{{ work.title }}</v-list-item-title>
                                    <v-list-item-subtitle>
                                        ID: {{ work.id }}
                                        <span v-if="work.title_en !== null" class="ml-2">{{ work.title_en }}</span>
                                    </v-list-item-subtitle>
                                </v-list-item>
                            </v-list>
                        </div>
                    </template>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn variant="text" @click="manual_link_dialog = false">閉じる</v-btn>
                    <v-btn variant="flat" color="secondary"
                        :disabled="selected_series_id === null || selected_work_id === null"
                        :loading="is_linking" @click="linkSelectedSeries()">
                        紐づける
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- 個人用アクセストークンは認証情報なので、通常の設定値とは分けて連携操作時だけ入力する -->
        <v-dialog width="550" v-model="accountLinkDialog">
            <v-card class="px-2 py-2">
                <v-card-title class="d-flex justify-center pt-6 font-weight-bold">Annict アカウントと連携</v-card-title>
                <v-card-text class="px-6 pt-4 pb-2">
                    <div class="mb-4">
                        Annict で作成した個人用アクセストークンを入力してください。<br>
                        視聴記録を投稿するには「読み込み + 書き込み」のスコープが必要です。
                    </div>
                    <v-text-field color="primary" variant="outlined" label="個人用アクセストークン" autocomplete="off"
                        :type="accessTokenShowing ? 'text' : 'password'"
                        :append-inner-icon="accessTokenShowing ? 'fa-solid:eye-slash' : 'fa-solid:eye'"
                        v-model="accessToken" @click:appendInner="accessTokenShowing = !accessTokenShowing">
                    </v-text-field>
                </v-card-text>
                <v-card-actions class="px-6 pb-5">
                    <v-spacer></v-spacer>
                    <v-btn variant="text" @click="closeAccountLinkDialog()">キャンセル</v-btn>
                    <v-btn color="secondary" variant="flat" :loading="linking" :disabled="accessToken.trim() === ''"
                        @click="loginAnnictAccount()">連携する</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </SettingsBase>
</template>
<script lang="ts" setup>

import { onMounted, ref } from 'vue';

import Message from '@/message';
import Annict, { IAnnictUnlinkedSeries, IAnnictWorkCandidate } from '@/services/Annict';
import useUserStore from '@/stores/UserStore';
import SettingsBase from '@/views/Settings/Base.vue';


const userStore = useUserStore();

// 手動紐づけダイアログの状態
const manual_link_dialog = ref(false);
const unlinked_series = ref<IAnnictUnlinkedSeries[]>([]);
const selected_series_id = ref<number | null>(null);
const work_search_query = ref('');
const work_candidates = ref<IAnnictWorkCandidate[]>([]);
const selected_work_id = ref<number | null>(null);
const is_loading_unlinked = ref(false);
const is_searching_works = ref(false);
const is_linking = ref(false);

// 個人用アクセストークンはダイアログを閉じるたびに破棄し、画面上へ残さない
const accountLinkDialog = ref(false);
const accessToken = ref('');
const accessTokenShowing = ref(false);
const linking = ref(false);
const isUpdatingAutoRecord = ref(false);
const isLoading = ref(true);


// URL から Annict 設定へ直接入った場合も、保存済み KonomiTV ログインセッションから連携状態を復元する
onMounted(async () => {
    await userStore.fetchUser();
    isLoading.value = false;
});


/**
 * Annict アカウント連携ダイアログを開く。
 */
function openAccountLinkDialog(): void {

    // KonomiTV ユーザーへ紐づける必要があるため、未ログイン状態では認証情報を入力させない
    if (userStore.user === null) {
        Message.warning('連携をはじめるには、KonomiTV アカウントにログインしてください。');
        return;
    }

    accountLinkDialog.value = true;
}


/**
 * Annict アカウント連携ダイアログを閉じる。
 */
function closeAccountLinkDialog(): void {

    accountLinkDialog.value = false;
    accessToken.value = '';
    accessTokenShowing.value = false;
}


/**
 * 入力された個人用アクセストークンで Annict アカウントを連携する。
 */
async function loginAnnictAccount(): Promise<void> {

    // 連打による同一認証リクエストの重複を防ぐ
    if (linking.value === true || accessToken.value.trim() === '') return;
    linking.value = true;

    try {
        const result = await Annict.loginAccount({access_token: accessToken.value});
        if (result === false) return;

        // 連携した公開プロフィールを画面へ反映し、入力済みトークンを破棄する
        await userStore.fetchUser(true);
        closeAccountLinkDialog();
        Message.success('Annict アカウントと連携しました。');
    } finally {
        linking.value = false;
    }
}


/**
 * 現在の KonomiTV ユーザーから Annict アカウント連携を解除する。
 */
async function logoutAnnictAccount(): Promise<void> {

    const result = await Annict.logoutAccount();
    if (result === false) return;

    // 連携解除後の未連携状態を画面へ反映する
    await userStore.fetchUser(true);
    Message.success('Annict アカウントとの連携を解除しました。');
}


/**
 * 視聴記録の自動投稿のオン・オフを保存する。
 * 公開ログへの投稿を伴うため、切り替えた内容を必ず通知する。
 * @param value 新しい設定値
 */
async function updateAutoRecordSetting(value: boolean | null): Promise<void> {

    // 連打や切り替えの競合を避ける
    if (isUpdatingAutoRecord.value === true) return;

    const enabled = value === true;
    isUpdatingAutoRecord.value = true;
    try {
        const result = await Annict.updateAutoRecord(enabled);
        if (result === false) return;

        // サーバー側の保存結果を画面へ反映する
        await userStore.fetchUser(true);
        if (enabled === true) {
            Message.warning('視聴完了したエピソードが Annict に公開記録されます。');
        } else {
            Message.info('Annict への自動記録をオフにしました。');
        }
    } finally {
        isUpdatingAutoRecord.value = false;
    }
}


/**
 * 手動紐づけダイアログを開き、未紐づけのシリーズを読み込む。
 */
async function openManualLinkDialog(): Promise<void> {

    is_loading_unlinked.value = true;
    try {
        const series_list = await Annict.fetchUnlinkedSeries();
        if (series_list === null) return;
        unlinked_series.value = series_list;
        selected_series_id.value = null;
        work_candidates.value = [];
        selected_work_id.value = null;
        work_search_query.value = '';
        manual_link_dialog.value = true;
    } finally {
        is_loading_unlinked.value = false;
    }
}


/**
 * シリーズが選ばれたら、そのタイトルで作品を検索する。
 */
async function onSeriesSelected(): Promise<void> {

    const series = unlinked_series.value.find(item => item.id === selected_series_id.value);
    if (series === undefined) return;
    // タイトルをそのまま検索語にして手間を省く
    work_search_query.value = series.title;
    selected_work_id.value = null;
    await searchWorks();
}


/**
 * 入力されたタイトルで Annict 作品を検索する。
 */
async function searchWorks(): Promise<void> {

    const query = work_search_query.value.trim();
    if (query === '' || is_searching_works.value === true) return;

    is_searching_works.value = true;
    try {
        const works = await Annict.searchWorks(query);
        if (works === null) return;
        work_candidates.value = works;
        selected_work_id.value = null;
    } finally {
        is_searching_works.value = false;
    }
}


/**
 * 選択されたシリーズを Annict 作品へ紐づける。
 */
async function linkSelectedSeries(): Promise<void> {

    if (selected_series_id.value === null || selected_work_id.value === null) return;
    if (is_linking.value === true) return;

    is_linking.value = true;
    try {
        const result = await Annict.linkSeries(selected_series_id.value, selected_work_id.value);
        if (result === false) return;
        Message.success('シリーズを Annict 作品へ紐づけました。');

        // 紐づけ済みのシリーズは一覧から取り除く
        unlinked_series.value = unlinked_series.value.filter(item => item.id !== selected_series_id.value);
        selected_series_id.value = null;
        selected_work_id.value = null;
        work_candidates.value = [];
    } finally {
        is_linking.value = false;
    }
}

</script>
<style lang="scss" scoped>

.annict-account {
    display: flex;
    align-items: center;
    min-height: 120px;
    padding: 20px;
    border-radius: 15px;
    background: rgb(var(--v-theme-background-lighten-2));
    @include tablet-horizontal {
        align-items: stretch;
        flex-direction: column;
    }
    @include smartphone-horizontal {
        align-items: stretch;
        flex-direction: column;
        padding: 16px;
        border-radius: 10px;
    }
    @include smartphone-vertical {
        align-items: stretch;
        flex-direction: column;
        padding: 16px 12px;
        border-radius: 10px;
    }

    &-wrapper {
        display: flex;
        align-items: center;
        min-width: 0;
    }

    &__icon {
        flex-shrink: 0;
        width: 80px;
        height: 80px;
        border-radius: 50%;
        object-fit: cover;
        background: linear-gradient(150deg, rgb(var(--v-theme-gray)), rgb(var(--v-theme-background-lighten-2)));
        @include smartphone-vertical {
            width: 60px;
            height: 60px;
        }
    }

    &__info {
        display: flex;
        flex-direction: column;
        min-width: 0;
        margin-left: 20px;
        margin-right: 16px;
        @include smartphone-vertical {
            margin-left: 12px;
            margin-right: 0;
        }

        &-name {
            overflow: hidden;
            font-size: 19px;
            font-weight: bold;
            text-overflow: ellipsis;
            white-space: nowrap;
            @include smartphone-vertical {
                font-size: 16px;
            }
        }

        &-description {
            margin-top: 6px;
            font-size: 13px;
            line-height: 1.5;
            color: rgb(var(--v-theme-text-darken-1));
        }
    }

    &__button,
    &__actions {
        flex-shrink: 0;
        @include tablet-horizontal {
            margin-top: 16px;
        }
        @include smartphone-horizontal {
            margin-top: 16px;
        }
        @include smartphone-vertical {
            margin-top: 16px;
        }
    }

    &__actions {
        display: flex;
        gap: 8px;
    }

    &--anonymous {
        @include smartphone-horizontal-short {
            .annict-account-wrapper > svg {
                display: none;
            }
            .annict-account__info {
                margin-left: 0 !important;
            }
        }
        @include smartphone-vertical {
            .annict-account-wrapper > svg {
                display: none;
            }
            .annict-account__info {
                margin-left: 0 !important;
            }
        }
    }
}

</style>
