<template>
    <div class="route-container">
        <HeaderBar />
        <main>
            <Navigation />
            <div class="captures-container-wrapper">
                <SPHeaderBar />
                <div class="captures-container">
                    <Breadcrumbs :crumbs="breadcrumbs" />
                    <!-- ヘッダー: タイトル・件数・フォルダ操作・並び順 -->
                    <div class="captures__header">
                        <h2 class="captures__title">
                            <span class="captures__title-text">{{ pageTitle }}</span>
                            <span class="captures__title-count" v-if="total > 0">{{ total }}件</span>
                            <!-- フォルダ表示中のみ、そのフォルダの名前変更・削除を出す -->
                            <v-btn v-if="activeFolder !== null" class="captures__title-action ml-2" variant="flat"
                                color="background-lighten-2" size="small" aria-label="フォルダ名を変更"
                                @click="openRenameFolderDialog(activeFolder)">
                                <Icon icon="fluent:rename-20-filled" width="18px" />
                            </v-btn>
                            <v-btn v-if="activeFolder !== null" class="captures__title-action ml-1" variant="flat"
                                color="background-lighten-2" size="small" aria-label="フォルダを削除"
                                @click="openDeleteFolderDialog(activeFolder)">
                                <Icon icon="fluent:delete-20-filled" width="18px" />
                            </v-btn>
                        </h2>
                        <div class="captures__actions">
                            <v-btn class="captures__selection-toggle" variant="flat" size="small"
                                :color="isSelectionMode ? 'primary' : 'background-lighten-2'"
                                @click="toggleSelectionMode()">
                                <Icon :icon="isSelectionMode ? 'fluent:dismiss-16-filled' : 'fluent:checkmark-square-20-regular'"
                                    width="17px" class="mr-1" />
                                {{ isSelectionMode ? '選択をやめる' : '選択' }}
                            </v-btn>
                            <v-select class="captures__sort" color="primary" bg-color="background-lighten-1"
                                variant="solo" density="comfortable" hide-details
                                :items="sortOptions" v-model="sortOrder" @update:model-value="updateSortOrder()">
                            </v-select>
                        </div>
                    </div>
                    <!-- フォルダのナビゲーション (検索結果では非表示) -->
                    <div class="captures__filters" v-if="isSearchMode === false && isLoggedIn">
                        <div class="captures__folder-chips">
                            <v-chip class="captures__chip" variant="elevated" size="small"
                                :color="activeFolderId === null ? 'primary' : undefined"
                                @click="navigateToFolder(null)">
                                すべて
                            </v-chip>
                            <v-chip class="captures__chip" variant="elevated" size="small"
                                v-for="folder in folders" :key="folder.id"
                                :color="activeFolderId === folder.id ? 'primary' : undefined"
                                @click="navigateToFolder(folder.id)">
                                <Icon icon="fluent:folder-20-filled" width="15px" class="mr-1" />
                                <span class="captures__chip-text">{{ folder.name }}</span>
                                <span class="captures__chip-count">{{ folder.capture_count }}</span>
                            </v-chip>
                            <v-chip class="captures__chip" variant="tonal" size="small" @click="openCreateFolderDialog()">
                                <Icon icon="fluent:add-20-filled" width="15px" class="mr-1" />
                                フォルダ作成
                            </v-chip>
                        </div>
                    </div>
                    <!-- キャプチャのグリッド (読み込み中・空状態を含む) -->
                    <div class="captures__grid" :class="{
                            'captures__grid--loading': isLoading,
                            'captures__grid--empty': total === 0 && isLoading === false,
                        }">
                        <div class="captures__empty" :class="{'captures__empty--show': total === 0 && isLoading === false}">
                            <div class="captures__empty-content">
                                <Icon class="captures__empty-icon" :icon="emptyIcon" width="54px" height="54px" />
                                <h2>{{ emptyMessage }}</h2>
                                <div class="captures__empty-submessage" v-if="emptySubMessage">
                                    {{ emptySubMessage }}
                                </div>
                            </div>
                        </div>
                        <div class="captures__grid-content">
                            <CaptureCard v-for="capture in captures" :key="capture.filename" :capture="capture"
                                :is-selected="selectedFilenames.has(capture.filename)"
                                :is-disabled="isSelectionMode && selectedFilenames.has(capture.filename) === false &&
                                    selectedFilenames.size >= MAX_SELECTION_COUNT"
                                :selection-number="selectedFilenames.size > 0 ? selectedOrder.indexOf(capture.filename) + 1 : 0"
                                @select="onCardSelect"
                                @toggle-selection="onCardToggleSelection" />
                        </div>
                    </div>
                    <!-- 選択モードの操作バー -->
                    <v-slide-y-reverse-transition>
                        <div class="captures__selection-bar" v-if="isSelectionMode && selectedFilenames.size > 0">
                            <span class="captures__selection-count">{{ selectedFilenames.size }}件選択中</span>
                            <v-btn variant="flat" color="primary" size="small" @click="openFolderSelectDialog()">
                                <Icon icon="fluent:folder-add-20-filled" width="17px" class="mr-1" />
                                フォルダに追加
                            </v-btn>
                            <v-btn v-if="activeFolderId !== null" variant="flat" color="warning" size="small"
                                @click="removeSelectedFromFolder()">
                                <Icon icon="fluent:folder-dismiss-20-filled" width="17px" class="mr-1" />
                                フォルダから削除
                            </v-btn>
                            <v-spacer />
                            <v-btn variant="text" size="small" @click="exitSelectionMode()">キャンセル</v-btn>
                        </div>
                    </v-slide-y-reverse-transition>
                    <!-- ページネーション -->
                    <div class="captures__pagination" v-if="total > PAGE_SIZE && isLoading === false">
                        <v-pagination :model-value="currentPage" active-color="primary" density="comfortable"
                            :length="Math.ceil(total / PAGE_SIZE)"
                            :total-visible="Utils.isSmartphoneVertical() ? 5 : 7"
                            @update:model-value="updatePage">
                        </v-pagination>
                    </div>
                </div>
            </div>
        </main>
        <!-- 拡大表示 -->
        <CaptureLightbox v-model="isLightboxOpen" :capture="lightboxCapture" :can-delete="isAdmin"
            @add-to-folder="openFolderSelectDialog([$event.filename])"
            @delete="openDeleteCaptureDialog" />
        <!-- キャプチャ削除の確認 -->
        <v-dialog max-width="450" v-model="isDeleteCaptureDialogOpen" persistent>
            <v-card>
                <v-card-title class="text-h6">キャプチャの削除</v-card-title>
                <v-card-text>
                    このキャプチャ画像をサーバーの保存先フォルダから削除しますか？<br>
                    この操作は取り消せません。
                </v-card-text>
                <v-card-actions>
                    <v-spacer />
                    <v-btn variant="text" @click="isDeleteCaptureDialogOpen = false">キャンセル</v-btn>
                    <v-btn variant="flat" color="error" :loading="isDeletingCapture" @click="executeDeleteCapture()">
                        削除
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
        <!-- フォルダ作成 -->
        <v-dialog max-width="450" v-model="isCreateFolderDialogOpen" persistent>
            <v-card>
                <v-card-title class="text-h6">フォルダ作成</v-card-title>
                <v-card-text>
                    <v-text-field v-model="newFolderName" label="フォルダ名" variant="outlined" density="comfortable"
                        hide-details autofocus maxlength="100" @keydown.enter="executeCreateFolder()" />
                </v-card-text>
                <v-card-actions>
                    <v-spacer />
                    <v-btn variant="text" @click="isCreateFolderDialogOpen = false">キャンセル</v-btn>
                    <v-btn variant="flat" color="primary" :loading="isCreatingFolder" :disabled="newFolderName.trim() === ''"
                        @click="executeCreateFolder()">
                        作成
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
        <!-- フォルダ名の変更 -->
        <v-dialog max-width="450" v-model="isRenameFolderDialogOpen" persistent>
            <v-card>
                <v-card-title class="text-h6">フォルダ名の変更</v-card-title>
                <v-card-text>
                    <v-text-field v-model="renameFolderName" label="フォルダ名" variant="outlined" density="comfortable"
                        hide-details autofocus maxlength="100" @keydown.enter="executeRenameFolder()" />
                </v-card-text>
                <v-card-actions>
                    <v-spacer />
                    <v-btn variant="text" @click="isRenameFolderDialogOpen = false">キャンセル</v-btn>
                    <v-btn variant="flat" color="primary" :loading="isRenamingFolder"
                        :disabled="renameFolderName.trim() === ''" @click="executeRenameFolder()">
                        変更
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
        <!-- フォルダ削除の確認 -->
        <v-dialog max-width="450" v-model="isDeleteFolderDialogOpen" persistent>
            <v-card>
                <v-card-title class="text-h6">フォルダの削除</v-card-title>
                <v-card-text>
                    フォルダ「{{ targetFolder?.name ?? '' }}」を削除しますか？<br>
                    フォルダ内のキャプチャ画像は削除されません。
                </v-card-text>
                <v-card-actions>
                    <v-spacer />
                    <v-btn variant="text" @click="isDeleteFolderDialogOpen = false">キャンセル</v-btn>
                    <v-btn variant="flat" color="error" :loading="isDeletingFolder" @click="executeDeleteFolder()">削除</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
        <!-- 追加先フォルダの選択 -->
        <v-dialog max-width="450" v-model="isFolderSelectDialogOpen">
            <v-card>
                <v-card-title class="text-h6">フォルダに追加</v-card-title>
                <v-card-text class="pb-0">
                    <v-list v-if="folders.length > 0" density="compact">
                        <v-list-item v-for="folder in folders" :key="folder.id" @click="addCapturesToFolder(folder.id)">
                            <template #prepend>
                                <Icon icon="fluent:folder-20-filled" width="20px" class="mr-2" />
                            </template>
                            <v-list-item-title>{{ folder.name }}</v-list-item-title>
                            <v-list-item-subtitle>{{ folder.capture_count }}件</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                    <div class="captures__folder-select-empty" v-else>
                        フォルダがありません。先にフォルダを作成してください。
                    </div>
                </v-card-text>
                <v-card-actions>
                    <v-spacer />
                    <v-btn variant="text" @click="isFolderSelectDialogOpen = false">閉じる</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>
<script lang="ts" setup>

import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import Breadcrumbs from '@/components/Breadcrumbs.vue';
import CaptureCard from '@/components/Captures/CaptureCard.vue';
import CaptureLightbox from '@/components/Captures/CaptureLightbox.vue';
import HeaderBar from '@/components/HeaderBar.vue';
import Navigation from '@/components/Navigation.vue';
import SPHeaderBar from '@/components/SPHeaderBar.vue';
import Message from '@/message';
import Captures, { ICapture, ICaptureFolder } from '@/services/Captures';
import useUserStore from '@/stores/UserStore';
import Utils from '@/utils';

// ルーター
const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

// 選択できるキャプチャの上限
const MAX_SELECTION_COUNT = 4;

// サーバー側のページサイズと揃える (グリッドの列数の公倍数)
// サーバー側の値をここで持つのは、総数から総ページ数を算出するため
const PAGE_SIZE = 36;

// ***** 一覧の状態 *****

// キャプチャのリストと総数
const captures = ref<ICapture[]>([]);
const total = ref(0);
const isLoading = ref(true);

// 現在のページ番号
const currentPage = ref(1);

// 並び順
const sortOrder = ref<'desc' | 'asc'>('desc');
const sortOptions = [
    {title: '新しい順', value: 'desc' as const},
    {title: '古い順', value: 'asc' as const},
];

// ***** 検索の状態 *****

// 検索モードかどうか (/captures/search の場合)
const isSearchMode = computed(() => route.path === '/captures/search');

// 検索キーワード (ヘッダーの検索欄から URL のクエリとして渡される)
const searchQuery = computed(() => typeof route.query.query === 'string' ? route.query.query : '');

// ***** フォルダの状態 *****

// フォルダ一覧
const folders = ref<ICaptureFolder[]>([]);

// 現在開いているフォルダ (null の場合はすべてのキャプチャ)
const activeFolderId = computed<number | null>(() => {
    const folderId = route.params.folder_id;
    if (typeof folderId !== 'string') {
        return null;
    }
    const parsedFolderId = Number.parseInt(folderId);
    return Number.isNaN(parsedFolderId) ? null : parsedFolderId;
});

// 現在開いているフォルダの情報
const activeFolder = computed<ICaptureFolder | null>(() =>
    folders.value.find((folder) => folder.id === activeFolderId.value) ?? null);

// フォルダ操作の対象
const targetFolder = ref<ICaptureFolder | null>(null);

// ***** 選択モードの状態 *****

// 選択モードかどうか
const isSelectionMode = ref(false);

// 選択中のキャプチャのファイル名 (選択した順序を保持するため配列で管理する)
const selectedOrder = ref<string[]>([]);
const selectedFilenames = computed(() => new Set(selectedOrder.value));

// ***** ダイアログの状態 *****

// 拡大表示
const isLightboxOpen = ref(false);
const lightboxCapture = ref<ICapture | null>(null);

// キャプチャ削除
const isDeleteCaptureDialogOpen = ref(false);
const isDeletingCapture = ref(false);

// フォルダ作成
const isCreateFolderDialogOpen = ref(false);
const newFolderName = ref('');
const isCreatingFolder = ref(false);

// フォルダ名の変更
const isRenameFolderDialogOpen = ref(false);
const renameFolderName = ref('');
const isRenamingFolder = ref(false);

// フォルダ削除
const isDeleteFolderDialogOpen = ref(false);
const isDeletingFolder = ref(false);

// 追加先フォルダの選択
const isFolderSelectDialogOpen = ref(false);
const folderAddTargetFilenames = ref<string[]>([]);

// ***** 権限 *****

// ログイン済みかどうか (未ログインではフォルダ機能を使えない)
const isLoggedIn = computed(() => userStore.is_logged_in);

// 管理者かどうか (キャプチャ画像の削除は管理者のみ許可される)
const isAdmin = computed(() => userStore.user?.is_admin === true);

// ***** 表示テキスト *****

// パンくずリスト
const breadcrumbs = computed(() => {
    const crumbs = [
        {name: 'ホーム', path: '/'},
        {name: 'キャプチャ', path: '/captures/', disabled: false},
    ];
    if (isSearchMode.value) {
        return [...crumbs, {name: '検索結果', path: '', disabled: true}];
    }
    if (activeFolder.value !== null) {
        return [...crumbs, {name: activeFolder.value.name, path: '', disabled: true}];
    }
    crumbs[1].disabled = true;
    return crumbs;
});

// ページタイトル
const pageTitle = computed(() => {
    if (isSearchMode.value) {
        return `「${searchQuery.value}」の検索結果`;
    }
    return activeFolder.value?.name ?? 'キャプチャ';
});

// 空状態のアイコン
const emptyIcon = computed(() => {
    if (isSearchMode.value) {
        return 'fluent:search-20-regular';
    }
    return activeFolder.value !== null ? 'fluent:folder-open-20-regular' : 'fluent:image-multiple-24-regular';
});

// 空状態の見出し
const emptyMessage = computed(() => {
    if (isSearchMode.value) {
        return '検索結果が見つかりませんでした。';
    }
    return activeFolder.value !== null ? 'このフォルダにはキャプチャがありません。' : 'まだキャプチャがありません。';
});

// 空状態の補足
const emptySubMessage = computed(() => {
    if (isSearchMode.value) {
        return '別のキーワードで検索してみてください。番組名・ファイル名・チャンネル名で検索できます。';
    }
    if (activeFolder.value !== null) {
        return 'キャプチャを選択して「フォルダに追加」すると、ここに表示されます。';
    }
    return 'テレビ・ビデオの視聴中にキャプチャすると、ここに表示されます。キャプチャの保存先が「サーバーにアップロード」になっているか確認してください。';
});

// ***** データ取得 *****

/**
 * 現在の表示条件 (フォルダ・検索・並び順・ページ) に合わせてキャプチャ一覧を取得する
 */
const fetchCaptures = async (): Promise<void> => {
    isLoading.value = true;
    let result;
    if (activeFolderId.value !== null) {
        result = await Captures.fetchFolderCaptures(activeFolderId.value, sortOrder.value, currentPage.value);
    } else {
        result = await Captures.fetchCaptures(sortOrder.value, currentPage.value, searchQuery.value || undefined);
    }
    if (result !== null) {
        captures.value = result.captures;
        total.value = result.total;
    }
    isLoading.value = false;
};

/**
 * ログインユーザーのフォルダ一覧を取得する
 * 未ログインの場合はフォルダ機能自体を使わないため、取得をスキップする
 */
const fetchFolders = async (): Promise<void> => {
    if (userStore.is_logged_in === false) {
        folders.value = [];
        return;
    }
    const result = await Captures.fetchFolders();
    if (result !== null) {
        folders.value = result.folders;
    }
};

// ***** ナビゲーション *****

/**
 * フォルダを切り替える
 * @param folderId 開くフォルダの ID (null の場合はすべてのキャプチャ)
 */
const navigateToFolder = async (folderId: number | null): Promise<void> => {
    // フォルダを移動したら選択状態は意味を失うため解除する
    exitSelectionMode();
    const path = folderId === null ? '/captures/' : `/captures/folders/${folderId}`;
    if (route.path === path) {
        return;
    }
    await router.push(path);
};

/**
 * ページを変更する
 * @param page 移動先のページ番号
 */
const updatePage = async (page: number): Promise<void> => {
    currentPage.value = page;
    isLoading.value = true;
    await router.replace({query: {...route.query, page: page.toString()}});
};

/**
 * 並び順を変更する
 * 並び順を変えた場合はページを先頭に戻す
 */
const updateSortOrder = async (): Promise<void> => {
    currentPage.value = 1;
    isLoading.value = true;
    await router.replace({query: {...route.query, order: sortOrder.value, page: '1'}});
};

// ***** 選択モード *****

/**
 * 選択モードを終了し、選択状態をすべて解除する
 */
const exitSelectionMode = (): void => {
    isSelectionMode.value = false;
    selectedOrder.value = [];
};

/**
 * 選択ボタンが押されたときの処理
 * 選択モードでなければ開始し、選択モード中なら終了する
 */
const toggleSelectionMode = (): void => {
    if (isSelectionMode.value) {
        exitSelectionMode();
        return;
    }
    isSelectionMode.value = true;
    selectedOrder.value = [];
};

/**
 * 選択状態を切り替える
 * @param capture 対象のキャプチャ
 */
const toggleSelection = (capture: ICapture): void => {
    if (selectedFilenames.value.has(capture.filename)) {
        selectedOrder.value = selectedOrder.value.filter((filename) => filename !== capture.filename);
    } else if (selectedOrder.value.length < MAX_SELECTION_COUNT) {
        // 上限に達している場合は追加しない (カード側で操作不可として表示されている)
        selectedOrder.value = [...selectedOrder.value, capture.filename];
    }
    // 選択が空になったら選択モードを抜ける
    if (selectedOrder.value.length === 0) {
        isSelectionMode.value = false;
    }
};

/**
 * カードがクリックされたときの処理
 * 選択モード中は選択の切り替え、通常時は拡大表示を行う
 * @param capture クリックされたキャプチャ
 */
const onCardSelect = (capture: ICapture): void => {
    if (isSelectionMode.value) {
        toggleSelection(capture);
        return;
    }
    lightboxCapture.value = capture;
    isLightboxOpen.value = true;
};

/**
 * カードが右クリック・長押しされたときの処理
 * 選択モードに入りつつ、そのキャプチャの選択を切り替える
 * @param capture 対象のキャプチャ
 */
const onCardToggleSelection = (capture: ICapture): void => {
    if (isSelectionMode.value === false) {
        isSelectionMode.value = true;
    }
    toggleSelection(capture);
};

// ***** キャプチャの削除 *****

/**
 * キャプチャ削除の確認ダイアログを開く
 * @param capture 削除対象のキャプチャ
 */
const openDeleteCaptureDialog = (capture: ICapture): void => {
    lightboxCapture.value = capture;
    isDeleteCaptureDialogOpen.value = true;
};

/**
 * キャプチャの削除を実行する
 * 削除に成功した場合は、拡大表示を閉じて一覧を取り直す
 */
const executeDeleteCapture = async (): Promise<void> => {
    if (lightboxCapture.value === null) {
        return;
    }
    isDeletingCapture.value = true;
    const success = await Captures.deleteCapture(lightboxCapture.value.filename);
    isDeletingCapture.value = false;
    if (success === false) {
        return;
    }

    Message.success('キャプチャを削除しました。');
    // 削除したキャプチャが選択されていた場合に備え、選択状態からも取り除く
    selectedOrder.value = selectedOrder.value.filter((filename) => filename !== lightboxCapture.value!.filename);
    isDeleteCaptureDialogOpen.value = false;
    isLightboxOpen.value = false;
    lightboxCapture.value = null;

    // 最後の 1 件を消した場合は前のページへ戻る (存在しないページを表示しないため)
    if (captures.value.length === 1 && currentPage.value > 1) {
        currentPage.value -= 1;
        await router.replace({query: {...route.query, page: currentPage.value.toString()}});
    }
    await Promise.all([fetchCaptures(), fetchFolders()]);
};

// ***** フォルダ操作 *****

// フォルダ作成ダイアログを開く
const openCreateFolderDialog = (): void => {
    newFolderName.value = '';
    isCreateFolderDialogOpen.value = true;
};

// フォルダを作成する
const executeCreateFolder = async (): Promise<void> => {
    const name = newFolderName.value.trim();
    if (name === '') {
        return;
    }
    isCreatingFolder.value = true;
    const created = await Captures.createFolder(name);
    isCreatingFolder.value = false;
    if (created === null) {
        return;
    }
    Message.success(`フォルダ「${created.name}」を作成しました。`);
    isCreateFolderDialogOpen.value = false;
    await fetchFolders();
};

// フォルダ名変更ダイアログを開く
const openRenameFolderDialog = (folder: ICaptureFolder): void => {
    targetFolder.value = folder;
    renameFolderName.value = folder.name;
    isRenameFolderDialogOpen.value = true;
};

// フォルダ名を変更する
const executeRenameFolder = async (): Promise<void> => {
    if (targetFolder.value === null) {
        return;
    }
    const name = renameFolderName.value.trim();
    if (name === '') {
        return;
    }
    isRenamingFolder.value = true;
    const updated = await Captures.updateFolder(targetFolder.value.id, {name});
    isRenamingFolder.value = false;
    if (updated === null) {
        return;
    }
    Message.success(`フォルダ名を「${updated.name}」に変更しました。`);
    isRenameFolderDialogOpen.value = false;
    await fetchFolders();
};

// フォルダ削除ダイアログを開く
const openDeleteFolderDialog = (folder: ICaptureFolder): void => {
    targetFolder.value = folder;
    isDeleteFolderDialogOpen.value = true;
};

// フォルダを削除する
const executeDeleteFolder = async (): Promise<void> => {
    if (targetFolder.value === null) {
        return;
    }
    const deletedFolder = targetFolder.value;
    isDeletingFolder.value = true;
    const success = await Captures.deleteFolder(deletedFolder.id);
    isDeletingFolder.value = false;
    if (success === false) {
        return;
    }
    Message.success(`フォルダ「${deletedFolder.name}」を削除しました。`);
    isDeleteFolderDialogOpen.value = false;

    // 削除したフォルダを表示中だった場合は、すべてのキャプチャ一覧へ戻る
    if (activeFolderId.value === deletedFolder.id) {
        await router.push('/captures/');
    }
    await fetchFolders();
};

// 追加先フォルダの選択ダイアログを開く
const openFolderSelectDialog = (filenames: string[] | undefined = undefined): void => {
    // 引数が無い場合は選択モードで選択中のキャプチャを対象にする
    folderAddTargetFilenames.value = filenames ?? [...selectedOrder.value];
    if (folderAddTargetFilenames.value.length === 0) {
        return;
    }
    isFolderSelectDialogOpen.value = true;
};

// 選択したフォルダへキャプチャを追加する
const addCapturesToFolder = async (folderId: number): Promise<void> => {
    const filenames = folderAddTargetFilenames.value;
    if (filenames.length === 0) {
        return;
    }
    const success = await Captures.addCapturesToFolder(folderId, filenames);
    if (success === false) {
        return;
    }
    const folder = folders.value.find((item) => item.id === folderId);
    Message.success(`${filenames.length}件のキャプチャを「${folder?.name ?? 'フォルダ'}」に追加しました。`);
    isFolderSelectDialogOpen.value = false;
    exitSelectionMode();
    await fetchFolders();
    // 追加先のフォルダを表示している場合は一覧も更新する
    if (activeFolderId.value === folderId) {
        await fetchCaptures();
    }
};

// 選択中のキャプチャを現在のフォルダから削除する
const removeSelectedFromFolder = async (): Promise<void> => {
    if (activeFolderId.value === null || selectedOrder.value.length === 0) {
        return;
    }
    const filenames = [...selectedOrder.value];
    const success = await Captures.removeCapturesFromFolder(activeFolderId.value, filenames);
    if (success === false) {
        return;
    }
    Message.success(`${filenames.length}件のキャプチャをフォルダから削除しました。`);
    exitSelectionMode();
    await Promise.all([fetchCaptures(), fetchFolders()]);
};

// ***** ルート変更の監視 *****

/**
 * URL のクエリからページ番号と並び順を復元する
 */
const syncStateFromRoute = (): void => {
    const page = Number.parseInt(typeof route.query.page === 'string' ? route.query.page : '1');
    currentPage.value = Number.isNaN(page) || page < 1 ? 1 : page;
    sortOrder.value = route.query.order === 'asc' ? 'asc' : 'desc';
};

// ページ・並び順・フォルダ・検索条件が変わったら一覧を取り直す
watch(() => route.fullPath, async () => {
    // 選択状態は表示中の一覧に紐づくため、条件が変わったら解除する
    isSelectionMode.value = false;
    selectedOrder.value = [];
    isLightboxOpen.value = false;
    syncStateFromRoute();
    await fetchCaptures();
}, {deep: true});

// ***** 初期化 *****

onMounted(async () => {
    // フォルダ機能と削除操作の可否はログイン状態に依存するため、最初にユーザー情報を取得する
    await userStore.fetchUser();

    syncStateFromRoute();
    await fetchFolders();

    // 存在しない・他ユーザーのフォルダを開こうとした場合は、すべてのキャプチャ一覧へ戻す
    // そのまま取得するとサーバーが 404 を返し、意図が伝わらないエラーだけが表示されてしまう
    if (isLoggedIn.value && activeFolderId.value !== null && activeFolder.value === null) {
        Message.error('指定されたキャプチャフォルダが見つかりませんでした。');
        await router.replace('/captures/');
        return;
    }

    await fetchCaptures();
});

</script>
<style lang="scss" scoped>

.captures-container-wrapper {
    display: flex;
    flex-direction: column;
    width: 100%;
    @include smartphone-vertical {
        padding-top: 10px;
    }
}

.captures-container {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 1000px;
    height: 100%;
    padding: 20px;
    margin: 0 auto;
    min-width: 0;
    @include smartphone-horizontal {
        padding: 16px 20px;
    }
    @include smartphone-vertical {
        padding: 8px 8px 16px;
    }
}

.captures__header {
    display: flex;
    align-items: center;
    @include smartphone-vertical {
        padding: 0 4px;
    }
}

.captures__title {
    display: flex;
    align-items: center;
    min-width: 0;
    padding-top: 8px;
    padding-bottom: 18px;
    font-size: 24px;
    font-weight: 700;
    @include smartphone-vertical {
        padding-bottom: 14px;
        font-size: 21px;
    }

    &-text {
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
    }

    &-count {
        flex-shrink: 0;
        margin-left: 10px;
        color: rgb(var(--v-theme-text-darken-1));
        font-size: 14px;
        font-weight: 400;
    }

    &-action {
        flex-shrink: 0;
        min-width: 34px !important;
        width: 34px;
        height: 34px;
        padding: 0 !important;
        border-radius: 8px;
    }
}

.captures__actions {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    gap: 8px;
    margin-left: auto;
    :deep(.v-field) {
        padding-right: 4px !important;
    }
    :deep(.v-field__input) {
        padding-right: 0 !important;
        padding-left: 10px !important;
    }
}

.captures__selection-toggle {
    height: 34px;
    font-size: 13px;
}

.captures__sort {
    width: 100px;
    :deep(.v-field__input) {
        min-height: unset !important;
        padding-top: 6px !important;
        padding-bottom: 6px !important;
        font-size: 13px !important;
    }
}

.captures__filters {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 12px;
    @include smartphone-vertical {
        padding: 0 4px;
        margin-bottom: 10px;
    }
}

.captures__folder-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.captures__chip {
    max-width: 220px;
    font-size: 12.5px;
    cursor: pointer;

    &-text {
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
    }

    &-count {
        margin-left: 5px;
        font-size: 11px;
        opacity: 0.7;
    }
}

.captures__grid {
    position: relative;
    width: 100%;
    border-radius: 8px;
    background: rgb(var(--v-theme-background-lighten-1));
    overflow: hidden;

    &--loading {
        .captures__grid-content {
            visibility: hidden;
            opacity: 0;
        }
    }

    &--empty {
        min-height: 220px;
    }
}

.captures__grid-content {
    display: grid;
    // デスクトップは4列。スマホ縦のみ2列にしてサムネイルの視認性を確保する
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    padding: 4px;
    width: 100%;
    transition: visibility 0.2s, opacity 0.2s;
    @include tablet-vertical {
        grid-template-columns: repeat(3, 1fr);
    }
    @include smartphone-horizontal {
        grid-template-columns: repeat(3, 1fr);
    }
    @include smartphone-vertical {
        grid-template-columns: repeat(2, 1fr);
    }
}

.captures__empty {
    display: flex;
    position: absolute;
    align-items: center;
    justify-content: center;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    padding: 28px 16px 40px;
    visibility: hidden;
    opacity: 0;
    transition: visibility 0.2s, opacity 0.2s;

    &--show {
        visibility: visible;
        opacity: 1;
    }

    &-content {
        text-align: center;

        h2 {
            font-size: 20px;
            @include smartphone-vertical {
                font-size: 18px;
            }
        }
    }

    &-icon {
        color: rgb(var(--v-theme-text-darken-1));
    }

    &-submessage {
        margin-top: 8px;
        color: rgb(var(--v-theme-text-darken-1));
        font-size: 14px;
        line-height: 1.7;
        @include smartphone-vertical {
            font-size: 12.5px;
        }
    }
}

.captures__selection-bar {
    display: flex;
    position: fixed;
    align-items: center;
    gap: 8px;
    bottom: 16px;
    left: 50%;
    padding: 8px 16px;
    border-radius: 12px;
    background: rgb(var(--v-theme-background-lighten-1));
    box-shadow: 0 4px 12px rgba(0, 0, 0, 30%);
    transform: translateX(-50%);
    z-index: 10;
    @include smartphone-vertical {
        right: 8px;
        bottom: 70px;
        left: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
        transform: none;
    }
}

.captures__selection-count {
    margin-right: 4px;
    font-size: 14px;
    font-weight: 600;
    white-space: nowrap;
}

.captures__pagination {
    display: flex;
    justify-content: center;
    margin-top: 22px;
}

.captures__folder-select-empty {
    padding: 16px 0;
    color: rgb(var(--v-theme-text-darken-1));
    text-align: center;
}

</style>
