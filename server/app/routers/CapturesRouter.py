
import asyncio
import errno
import hashlib
import io
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

import puremagic
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from puremagic import PureError

from app import logging, schemas
from app.config import Config
from app.models.CaptureBookmark import CaptureBookmark
from app.models.CaptureFolder import CaptureFolder
from app.models.Channel import Channel
from app.models.User import User
from app.routers.UsersRouter import GetCurrentAdminUser, GetCurrentUser


# ルーター
router = APIRouter(
    tags = ['Captures'],
    prefix = '/api/captures',
)

# キャプチャ一覧 API の1ページあたりの表示件数
## グリッドの列数 (デスクトップ: 4列, スマホ横: 3列, スマホ縦: 2列) の公倍数にして、
## 最終行だけ極端に列数が少なくなる状態を避ける (4, 3, 2 の最小公倍数は 12)
PAGE_SIZE = 36

# サムネイル画像の長辺の最大サイズ (ピクセル)
THUMBNAIL_MAX_SIZE = 400

# キャプチャ画像として扱う拡張子
CAPTURE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}

# EXIF の XPComment タグ番号 (Microsoft 拡張のコメント領域)
## クライアント側の CaptureCompositor が UCS-2 (UTF-16-LE) の JSON を書き込んでいる
XP_COMMENT_TAG = 0x9C9C

# フォルダ名の最大文字数
## 画面幅の狭いスマートフォンでも判別できる長さに抑え、極端に長い名前でレイアウトが崩れるのを防ぐ
FOLDER_NAME_MAX_LENGTH = 100


def GetUploadFolders() -> list[Path]:
    """
    サーバー設定で指定されたキャプチャ画像の保存先フォルダのうち、実在するものだけを返す。

    Returns:
        list[Path]: 実在する保存先フォルダのパスのリスト (設定順)。
    """

    # 保存先フォルダは設定ファイル次第で存在しないことがあるため、ここで必ず実在確認する
    return [Path(folder) for folder in Config().capture.upload_folders if Path(folder).is_dir()]


def FindCaptureFile(filename: str) -> Path | None:
    """
    ファイル名からキャプチャ画像のフルパスを解決する。ディレクトリトラバーサル対策を含む。

    Args:
        filename (str): キャプチャ画像のファイル名 (拡張子を含む)。

    Returns:
        Path | None: 見つかったキャプチャ画像のフルパス。無効な名前・未存在の場合は None。
    """

    # 空文字・ディレクトリ区切り・親ディレクトリ参照を含む名前は、そもそもキャプチャのファイル名として不正
    ## URL デコードの結果 '/' がここへ到達する経路があるため、resolve() 任せにせず明示的に弾く
    if filename in ('', '.', '..') or '/' in filename or '\\' in filename:
        return None

    # キャプチャ画像以外の拡張子を配信・削除しないよう、ホワイトリスト方式で制限する
    if Path(filename).suffix.lower() not in CAPTURE_EXTENSIONS:
        return None

    for upload_folder in GetUploadFolders():
        # ディレクトリトラバーサル対策のためのチェック
        ## ref: https://stackoverflow.com/a/45190125/17124142
        try:
            upload_folder.joinpath(filename).resolve().relative_to(upload_folder.resolve())
        except ValueError:
            return None

        filepath = upload_folder / filename
        if filepath.is_file():
            return filepath

    # どの保存先フォルダにも存在しなかった
    return None


def ExtractCaptureMetadata(filepath: Path) -> schemas.CaptureMetadata | None:
    """
    キャプチャ画像の EXIF XPComment からメタデータを抽出する。

    Pillow の getexif() は画像ヘッダーのみを読み、ピクセルデータのデコードは行わない。
    このため一覧・検索のたびに全件へ適用しても現実的なコストに収まる。

    Args:
        filepath (Path): キャプチャ画像のフルパス。

    Returns:
        schemas.CaptureMetadata | None: 抽出できたメタデータ。EXIF が無い・壊れている場合は None。
    """

    try:
        with Image.open(filepath) as image:
            exif = image.getexif()
            if XP_COMMENT_TAG not in exif:
                return None

            # Pillow は XPComment を bytes で返すが、環境によっては str になることもある
            raw_comment = exif[XP_COMMENT_TAG]
            if isinstance(raw_comment, bytes):
                # UCS-2 (UTF-16-LE) でデコードし、末尾のヌル終端を除去する
                comment = raw_comment.decode('utf-16-le').rstrip('\x00')
            else:
                comment = str(raw_comment).rstrip('\x00')

            # メタデータはクライアントが書き込んだ JSON なので、想定外の値が来ても一覧自体は壊さない
            try:
                return schemas.CaptureMetadata(**json.loads(comment))
            except Exception:
                # 古いクライアントが書き込んだ別形式のコメントなどが該当する
                return None
    except (UnidentifiedImageError, OSError, ValueError):
        # 画像として開けないファイルでも一覧からは消さず、メタデータ無しとして扱う
        return None


def ExtractCaptureInfo(filepath: Path) -> schemas.Capture:
    """
    キャプチャ画像ファイルから一覧表示に必要な情報を抽出する。

    Args:
        filepath (Path): キャプチャ画像のフルパス。

    Returns:
        schemas.Capture: キャプチャ画像の情報。画像が壊れている場合は幅・高さを 0 として返す。
    """

    stat = filepath.stat()

    # 拡張子から MIME タイプを決める (アップロード時に JPEG / PNG のみ許可しているため、この2種類で足りる)
    suffix = filepath.suffix.lower()
    mime_type: Literal['image/jpeg', 'image/png'] = 'image/jpeg' if suffix in ('.jpg', '.jpeg') else 'image/png'

    # 画像サイズの取得に失敗しても、一覧からキャプチャ自体を消してしまわない
    image_width = 0
    image_height = 0
    try:
        with Image.open(filepath) as image:
            image_width = image.width
            image_height = image.height
    except (UnidentifiedImageError, OSError, ValueError):
        logging.warning(f'[CapturesRouter][ExtractCaptureInfo] Failed to read image size: {filepath.name}')

    return schemas.Capture(
        image_width = image_width,
        image_height = image_height,
        filename = filepath.name,
        file_size = stat.st_size,
        file_modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        mime_type = mime_type,
        capture_metadata = ExtractCaptureMetadata(filepath),
    )


def CollectCaptureFiles() -> list[tuple[str, float, Path]]:
    """
    すべての保存先フォルダ直下からキャプチャ画像ファイルを収集する。

    os.scandir() を使い、stat 情報を個別に取得するより少ない syscall で済ませる。
    同じファイル名が複数の保存先フォルダに存在する場合は、設定順で先に見つかったものを採用する。

    Returns:
        list[tuple[str, float, Path]]: (ファイル名, 更新日時 (epoch 秒), フルパス) のリスト。
    """

    capture_files: list[tuple[str, float, Path]] = []
    seen_filenames: set[str] = set()

    for upload_folder in GetUploadFolders():
        try:
            with os.scandir(upload_folder) as entries:
                for entry in entries:
                    # サブフォルダはキャプチャの保存先ではないため対象外
                    ## 壊れたシンボリックリンクなどは is_file() が False になるので同時に除外できる
                    if entry.is_file() is False:
                        continue

                    # キャプチャ画像の拡張子以外は対象外
                    name_lower = entry.name.lower()
                    if not any(name_lower.endswith(extension) for extension in CAPTURE_EXTENSIONS):
                        continue

                    # 同じファイル名が先の保存先フォルダにあった場合は、そちらを正とする
                    if entry.name in seen_filenames:
                        continue
                    seen_filenames.add(entry.name)

                    capture_files.append((entry.name, entry.stat().st_mtime, Path(entry.path)))
        except OSError as ex:
            # ネットワーク共有が一時的に落ちている場合などでも、他の保存先フォルダの一覧は返す
            logging.warning(f'[CapturesRouter][CollectCaptureFiles] Failed to scan folder {upload_folder}: {ex}')

    return capture_files


def FilterCaptureFilesBySearch(
    capture_files: list[tuple[str, float, Path]],
    search: str,
    search_channel_ids: set[tuple[int | None, int | None]],
) -> list[tuple[str, float, Path]]:
    """
    キャプチャファイルを、ファイル名・番組名・チャンネル名のいずれかで部分一致検索する。

    Args:
        capture_files (list[tuple[str, float, Path]]): 検索対象のキャプチャファイル。
        search (str): 検索キーワード。
        search_channel_ids (set[tuple[int | None, int | None]]): キーワードに一致するチャンネルの (network_id, service_id)。

    Returns:
        list[tuple[str, float, Path]]: 条件に一致したキャプチャファイル。
    """

    search_lower = search.lower()
    matched_files: list[tuple[str, float, Path]] = []

    # EXIF を読まなくても判定できるファイル名一致を先に処理し、残りだけメタデータを読む
    metadata_targets: list[tuple[str, float, Path]] = []
    for capture_file in capture_files:
        if search_lower in capture_file[0].lower():
            matched_files.append(capture_file)
        else:
            metadata_targets.append(capture_file)

    for filename, modified_at, filepath in metadata_targets:
        metadata = ExtractCaptureMetadata(filepath)
        if metadata is None:
            continue
        # 番組名での一致
        if search_lower in metadata.title.lower():
            matched_files.append((filename, modified_at, filepath))
            continue
        # チャンネル名での一致 (EXIF にチャンネル名は無いため、解決済みのチャンネル ID と照合する)
        if (metadata.network_id, metadata.service_id) in search_channel_ids:
            matched_files.append((filename, modified_at, filepath))

    return matched_files


def BuildCapturePage(
    capture_files: list[tuple[str, float, Path]],
    order: Literal['desc', 'asc'],
    page: int,
) -> schemas.Captures:
    """
    キャプチャファイルのリストを、並べ替えとページネーションを適用したレスポンスへ変換する。

    Args:
        capture_files (list[tuple[str, float, Path]]): 対象のキャプチャファイル。
        order (Literal['desc', 'asc']): ソート順序。
        page (int): ページ番号 (1始まり)。

    Returns:
        schemas.Captures: 総数と現在のページのキャプチャ情報。
    """

    # 更新日時で並べ替える (同じファイル名は保存先フォルダの優先順で一意になっている)
    capture_files.sort(key=lambda item: item[1], reverse = (order == 'desc'))

    # 総数はページネーション適用前に確定させる
    total = len(capture_files)

    # 情報抽出は重いので、現在のページに含まれるファイルだけを対象にする
    offset = (page - 1) * PAGE_SIZE
    page_files = capture_files[offset:offset + PAGE_SIZE]
    return schemas.Captures(
        total = total,
        captures = [ExtractCaptureInfo(item[2]) for item in page_files],
    )


def BuildETag(filepath: Path, thumbnail: bool) -> str:
    """
    キャプチャ画像レスポンス用の ETag を生成する。

    ファイル内容のハッシュではなく (パス, 更新時刻, サイズ, サムネイル可否) から作るため、
    大きな画像でも追加の読み込みが発生しない。

    Args:
        filepath (Path): キャプチャ画像のフルパス。
        thumbnail (bool): サムネイル画像としての ETag かどうか。

    Returns:
        str: ダブルクォートで囲まれた ETag 文字列。
    """

    stat = filepath.stat()
    source = f'{filepath.name}:{stat.st_mtime_ns}:{stat.st_size}:{"thumb" if thumbnail else "full"}'
    return f'"{hashlib.sha1(source.encode()).hexdigest()}"'


def IsNotModified(if_none_match: str | None, etag: str) -> bool:
    """
    If-None-Match ヘッダーから 304 Not Modified を返すべきか判定する。

    Args:
        if_none_match (str | None): リクエストの If-None-Match ヘッダー。
        etag (str): 現在のリソースの ETag。

    Returns:
        bool: 304 を返すべき場合は True。
    """

    # 未指定なら必ず 200 で返す
    if if_none_match is None:
        return False

    # "*" はリソースが存在する限り常に一致する
    if if_none_match.strip() == '*':
        return True

    # カンマ区切りの候補のいずれかと一致すれば 304
    return etag in [candidate.strip() for candidate in if_none_match.split(',')]


def GenerateThumbnail(filepath: Path) -> bytes:
    """
    キャプチャ画像を一覧表示用のサムネイル (JPEG) に変換する。

    Args:
        filepath (Path): キャプチャ画像のフルパス。

    Returns:
        bytes: エンコードされた JPEG のバイト列。

    Raises:
        HTTPException: 画像を開けない、またはサムネイルを生成できない場合。
    """

    try:
        with Image.open(filepath) as image:
            # EXIF の回転情報を適用してから縮小する (縦向きのキャプチャが横倒しにならないように)
            transposed = ImageOps.exif_transpose(image)
            resized = transposed if transposed is not None else image
            resized.thumbnail((THUMBNAIL_MAX_SIZE, THUMBNAIL_MAX_SIZE), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            # PNG (透過を含む場合がある) は JPEG として保存できないため RGB に変換する
            if resized.mode not in ('RGB', 'L'):
                resized = resized.convert('RGB')
            resized.save(buffer, format='JPEG', quality=80)
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as ex:
        logging.error(f'[CapturesRouter][GenerateThumbnail] Failed to generate thumbnail: {filepath.name}', exc_info=ex)
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Failed to generate thumbnail',
        )


async def GetOwnedFolder(folder_id: int, current_user: User) -> CaptureFolder:
    """
    ログインユーザーが所有するキャプチャフォルダを取得する。

    他ユーザーのフォルダは存在自体を伏せるため、403 ではなく 404 を返す。

    Args:
        folder_id (int): 取得するフォルダの ID。
        current_user (User): ログイン中のユーザー。

    Returns:
        CaptureFolder: 取得したフォルダ。

    Raises:
        HTTPException: フォルダが存在しない、または他ユーザーの所有物の場合。
    """

    folder = await CaptureFolder.filter(id=folder_id, user=current_user).first()
    if folder is None:
        logging.warning(f'[CapturesRouter][GetOwnedFolder] Capture folder was not found. [folder_id: {folder_id}]')
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail = 'Capture folder not found',
        )
    return folder


async def BuildCaptureFolderSchema(folder: CaptureFolder) -> schemas.CaptureFolder:
    """
    フォルダのモデルを、登録件数を含む API スキーマに変換する。

    Args:
        folder (CaptureFolder): 変換するフォルダのモデル。

    Returns:
        schemas.CaptureFolder: 登録件数を含むフォルダのスキーマ。
    """

    # フォルダ数は高々数十件程度なので、集計クエリを組み立てるより単純に件数を数える方が読みやすい
    ## ここで数えるのはブックマークの件数で、実ファイルが消えたものも含む (一覧側では除外される)
    capture_count = await CaptureBookmark.filter(folder=folder).count()
    return schemas.CaptureFolder(
        id = folder.id,
        name = folder.name,
        sort_order = folder.sort_order,
        capture_count = capture_count,
        created_at = folder.created_at,
        updated_at = folder.updated_at,
    )


def ValidateFolderName(name: str) -> str:
    """
    フォルダ名を検証し、前後の空白を除去した名前を返す。

    Args:
        name (str): 検証するフォルダ名。

    Returns:
        str: 前後の空白を除去したフォルダ名。

    Raises:
        HTTPException: 空文字、または長すぎる場合。
    """

    stripped_name = name.strip()
    if stripped_name == '':
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Folder name cannot be empty',
        )
    if len(stripped_name) > FOLDER_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = f'Folder name must be {FOLDER_NAME_MAX_LENGTH} characters or less',
        )
    return stripped_name


# ***** キャプチャ一覧 API *****


@router.get(
    '',
    summary = 'キャプチャ一覧 API',
    response_model = schemas.Captures,
)
async def CaptureListAPI(
    order: Annotated[Literal['desc', 'asc'], Query(description='ソート順序 (desc: 新しい順, asc: 古い順)。')] = 'desc',
    page: Annotated[int, Query(description='ページ番号 (1始まり)。', ge=1)] = 1,
    search: Annotated[str | None, Query(description='ファイル名・番組名・チャンネル名での部分一致検索キーワード。')] = None,
):
    """
    サーバーに保存されたキャプチャ画像の一覧を取得する。<br>
    保存先フォルダ直下の JPEG / PNG を走査し、ファイルの更新日時順に並べて返す。<br>
    EXIF メタデータの読み取りは重いため、ページネーション適用後のファイルにのみ行う。
    """

    # ファイル走査は同期 I/O なので、イベントループを止めないようスレッドへ逃がす
    capture_files = await asyncio.to_thread(CollectCaptureFiles)

    # 検索語に一致するチャンネルの (network_id, service_id) を先に集めておく
    ## キャプチャの EXIF にはチャンネル名が入っていないため、チャンネル名検索は ID の照合で実現する
    if search:
        matching_channels = await Channel.filter(name__icontains=search).all()
        search_channel_ids: set[tuple[int | None, int | None]] = {
            (channel.network_id, channel.service_id) for channel in matching_channels
        }
        # 検索時は全件の EXIF を読む必要があるため、まとめて1回のスレッド実行で処理する
        capture_files = await asyncio.to_thread(FilterCaptureFilesBySearch, capture_files, search, search_channel_ids)

    # 並べ替えとページネーション、情報抽出は同期 I/O を含むためスレッドへ逃がす
    return await asyncio.to_thread(BuildCapturePage, capture_files, order, page)


# ***** キャプチャフォルダ CRUD API *****


@router.get(
    '/folders',
    summary = 'キャプチャフォルダ一覧 API',
    response_model = schemas.CaptureFolders,
)
async def CaptureFolderListAPI(
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    ログインユーザーが作成したキャプチャフォルダの一覧を表示順に取得する。<br>
    各フォルダには登録されているキャプチャの件数が含まれる。
    """

    folder_models = await CaptureFolder.filter(user=current_user).order_by('sort_order', 'id')
    folders = [await BuildCaptureFolderSchema(folder) for folder in folder_models]
    return schemas.CaptureFolders(total = len(folders), folders = folders)


@router.post(
    '/folders',
    summary = 'キャプチャフォルダ作成 API',
    response_model = schemas.CaptureFolder,
    status_code = status.HTTP_201_CREATED,
)
async def CaptureFolderCreateAPI(
    request: schemas.CaptureFolderCreateRequest,
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    新しいキャプチャフォルダを作成する。<br>
    表示順序は既存フォルダの最大値 + 1 が自動設定される。
    """

    name = ValidateFolderName(request.name)

    # 既存フォルダの末尾に並ぶよう、最大の表示順序 + 1 を割り当てる
    last_folder = await CaptureFolder.filter(user=current_user).order_by('-sort_order').first()
    sort_order = (last_folder.sort_order + 1) if last_folder is not None else 0

    folder = await CaptureFolder.create(user=current_user, name=name, sort_order=sort_order)
    return await BuildCaptureFolderSchema(folder)


@router.put(
    '/folders/{folder_id}',
    summary = 'キャプチャフォルダ更新 API',
    response_model = schemas.CaptureFolder,
)
async def CaptureFolderUpdateAPI(
    folder_id: int,
    request: schemas.CaptureFolderUpdateRequest,
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    指定されたキャプチャフォルダの名前・表示順序を更新する。<br>
    他ユーザーのフォルダは操作できない。
    """

    folder = await GetOwnedFolder(folder_id, current_user)

    # 指定されたフィールドのみ更新する (None は「変更しない」を意味する)
    update_fields: list[str] = []
    if request.name is not None:
        folder.name = ValidateFolderName(request.name)
        update_fields.append('name')
    if request.sort_order is not None:
        folder.sort_order = request.sort_order
        update_fields.append('sort_order')

    # 変更点が無い場合は無駄な UPDATE を発行しない (updated_at は auto_now で自動更新される)
    if update_fields:
        await folder.save(update_fields=update_fields)

    return await BuildCaptureFolderSchema(folder)


@router.delete(
    '/folders/{folder_id}',
    summary = 'キャプチャフォルダ削除 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def CaptureFolderDeleteAPI(
    folder_id: int,
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    指定されたキャプチャフォルダを削除する。<br>
    紐付いていたブックマークも CASCADE で削除されるが、キャプチャ画像の実ファイルは削除しない。
    """

    folder = await GetOwnedFolder(folder_id, current_user)
    await folder.delete()


# ***** フォルダ内キャプチャ操作 API *****


@router.get(
    '/folders/{folder_id}/captures',
    summary = 'フォルダ内キャプチャ一覧 API',
    response_model = schemas.Captures,
)
async def CaptureFolderCaptureListAPI(
    folder_id: int,
    current_user: Annotated[User, Depends(GetCurrentUser)],
    order: Annotated[Literal['desc', 'asc'], Query(description='ソート順序 (desc: 新しい順, asc: 古い順)。')] = 'desc',
    page: Annotated[int, Query(description='ページ番号 (1始まり)。', ge=1)] = 1,
):
    """
    指定されたフォルダに登録されているキャプチャの一覧を取得する。<br>
    ブックマークはファイル名しか持たないため、実ファイルが存在しないものは一覧から除外する。
    """

    folder = await GetOwnedFolder(folder_id, current_user)
    bookmarks = await CaptureBookmark.filter(folder=folder).all()

    def CollectBookmarkedFiles() -> list[tuple[str, float, Path]]:
        """
        ブックマークのうち実ファイルが存在するものだけを収集する。

        Returns:
            list[tuple[str, float, Path]]: (ファイル名, 更新日時, フルパス) のリスト。
        """

        collected: list[tuple[str, float, Path]] = []
        for bookmark in bookmarks:
            filepath = FindCaptureFile(bookmark.filename)
            if filepath is None:
                # サーバー PC 上で直接削除されたキャプチャは、黙って一覧から外す
                continue
            collected.append((bookmark.filename, filepath.stat().st_mtime, filepath))
        return collected

    capture_files = await asyncio.to_thread(CollectBookmarkedFiles)
    return await asyncio.to_thread(BuildCapturePage, capture_files, order, page)


@router.post(
    '/folders/{folder_id}/captures',
    summary = 'キャプチャをフォルダに追加 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def CaptureFolderCaptureAddAPI(
    folder_id: int,
    request: schemas.CaptureBookmarkRequest,
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    指定されたフォルダへキャプチャを一括追加する。<br>
    実ファイルが存在しないファイル名と、既に登録済みのファイル名は無視する。
    """

    folder = await GetOwnedFolder(folder_id, current_user)

    # 重複登録を防ぐため、既に登録済みのファイル名を先に取得しておく
    existing_bookmarks = await CaptureBookmark.filter(folder=folder).all()
    existing_filenames = {bookmark.filename for bookmark in existing_bookmarks}

    # 実ファイルの存在確認は同期 I/O なのでスレッドへ逃がし、登録できるファイル名だけを返してもらう
    ## dict.fromkeys() でリクエスト内の同じファイル名の重複もまとめて除去する
    candidate_filenames = [filename for filename in dict.fromkeys(request.filenames) if filename not in existing_filenames]
    registered_filenames = await asyncio.to_thread(
        lambda: [filename for filename in candidate_filenames if FindCaptureFile(filename) is not None],
    )

    # 実ファイルが無いファイル名を登録すると、一覧に出ない幽霊レコードになるためスキップした旨を記録する
    for filename in candidate_filenames:
        if filename not in registered_filenames:
            logging.warning(
                f'[CapturesRouter][CaptureFolderCaptureAddAPI] Capture file was not found, skipping: {filename}',
            )

    if registered_filenames:
        await CaptureBookmark.bulk_create([
            CaptureBookmark(folder=folder, filename=filename) for filename in registered_filenames
        ])


@router.delete(
    '/folders/{folder_id}/captures',
    summary = 'キャプチャをフォルダから削除 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def CaptureFolderCaptureRemoveAPI(
    folder_id: int,
    request: schemas.CaptureBookmarkRequest,
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    指定されたフォルダからキャプチャの登録を一括解除する。<br>
    ブックマークを削除するだけで、キャプチャ画像の実ファイルは削除しない。
    """

    folder = await GetOwnedFolder(folder_id, current_user)
    await CaptureBookmark.filter(folder=folder, filename__in=request.filenames).delete()


# ***** キャプチャ画像の取得・削除・アップロード API *****


@router.get(
    '/{filename}',
    summary = 'キャプチャ画像取得 API',
    response_class = Response,
)
def CaptureImageAPI(
    filename: str,
    if_none_match: Annotated[str | None, Header(description='キャッシュ検証用の ETag。')] = None,
    thumbnail: Annotated[bool, Query(description='サムネイル画像を返すかどうか。')] = False,
):
    """
    指定されたファイル名のキャプチャ画像を返す。<br>
    thumbnail=true を指定すると、一覧表示用に縮小した JPEG を返す。<br>
    同期ファイル I/O を伴うため敢えて同期関数として実装している。
    """

    filepath = FindCaptureFile(filename)
    if filepath is None:
        logging.error(f'[CapturesRouter][CaptureImageAPI] Capture file was not found: {filename}')
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail = 'Capture file not found',
        )

    # ブラウザキャッシュを有効にしつつ、ファイルが差し替わった場合は確実に再取得させる
    ## private を指定するのは、キャプチャがログインユーザーの私的な画像であるため
    etag = BuildETag(filepath, thumbnail)
    if IsNotModified(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={'ETag': etag})

    if thumbnail:
        return Response(
            content = GenerateThumbnail(filepath),
            media_type = 'image/jpeg',
            headers = {
                'Cache-Control': 'private, max-age=86400',
                'ETag': etag,
            },
        )

    try:
        content = filepath.read_bytes()
    except OSError as ex:
        logging.error(f'[CapturesRouter][CaptureImageAPI] Failed to read capture file: {filename}', exc_info=ex)
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Failed to read capture file',
        )

    suffix = filepath.suffix.lower()
    media_type = 'image/jpeg' if suffix in ('.jpg', '.jpeg') else 'image/png'
    return Response(
        content = content,
        media_type = media_type,
        headers = {
            'Cache-Control': 'private, max-age=86400',
            'ETag': etag,
        },
    )


@router.delete(
    '/{filename}',
    summary = 'キャプチャ画像削除 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def CaptureDeleteAPI(
    filename: str,
    current_user: Annotated[User, Depends(GetCurrentAdminUser)],
):
    """
    指定されたファイル名のキャプチャ画像を、サーバーの保存先フォルダから削除する。<br>
    不可逆な操作であるため、管理者アカウントでないと実行できない。<br>
    削除したキャプチャを参照しているフォルダのブックマークも同時に削除する。
    """

    filepath = FindCaptureFile(filename)
    if filepath is None:
        logging.error(f'[CapturesRouter][CaptureDeleteAPI] Capture file was not found: {filename}')
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail = 'Capture file not found',
        )

    # 実ファイルの削除は同期 I/O なのでスレッドへ逃がす
    try:
        await asyncio.to_thread(filepath.unlink)
    except PermissionError:
        logging.error(f'[CapturesRouter][CaptureDeleteAPI] Permission denied to delete the file: {filename}')
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Permission denied to delete the file',
        )
    except OSError as ex:
        logging.error(f'[CapturesRouter][CaptureDeleteAPI] Failed to delete the file: {filename}', exc_info=ex)
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Unexpected error occurred while deleting the file',
        )

    # 実ファイルが消えたブックマークは以後どの一覧にも現れないため、ここで掃除しておく
    ## 全ユーザーのフォルダに同じファイル名が登録され得るので、ユーザーで絞らず削除する
    deleted_bookmarks = await CaptureBookmark.filter(filename=filename).delete()
    if deleted_bookmarks > 0:
        logging.info(
            f'[CapturesRouter][CaptureDeleteAPI] Removed {deleted_bookmarks} capture bookmark(s): {filename}',
        )


@router.post(
    '',
    summary = 'キャプチャ画像アップロード API',
    status_code = status.HTTP_204_NO_CONTENT,
)
def CaptureUploadAPI(
    image: Annotated[UploadFile, File(description='アップロードするキャプチャ画像 (JPEG or PNG)。')],
):
    """
    クライアント側でキャプチャした画像をサーバーにアップロードする。<br>
    アップロードされた画像は、サーバー設定で指定されたフォルダに保存される。<br>
    同期ファイル I/O を伴うため敢えて同期関数として実装している。
    """

    # 画像が JPEG または PNG かをチェック
    ## 万が一悪意ある攻撃者から危険なファイルを送り込まれないように
    ## 拡張子や Content-Type は送信側が自由に名乗れるため、必ずファイル内容 (マジックバイト) で判定する
    try:
        mimetype: str = puremagic.magic_stream(image.file)[0].mime_type
    except (PureError, IndexError):
        # 既知の形式に当てはまらないファイルは puremagic が PureError を投げる
        ## ここで捕捉しないと 422 ではなく 500 になり、クライアント側のエラー処理から外れてしまう
        logging.error('[CapturesRouter][CaptureUploadAPI] Uploaded file was not a known image format.')
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Please upload JPEG or PNG image',
        )
    if mimetype != 'image/jpeg' and mimetype != 'image/png':
        logging.error('[CapturesRouter][CaptureUploadAPI] Invalid image file was uploaded.')
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Please upload JPEG or PNG image',
        )

    # シークを元に戻す（重要）
    ## puremagic を使った時点でファイルはシークされているため、戻さないと 0 バイトになる
    image.file.seek(0)

    # 先頭から順に保存容量が空いている保存先フォルダを探す
    upload_folders: list[Path] = [Path(folder) for folder in Config().capture.upload_folders]
    for index, upload_folder in enumerate(upload_folders):

        # 万が一保存先フォルダが存在しない場合は次の保存先フォルダを探す
        if not upload_folder.exists():
            continue

        # 保存先フォルダの空き容量が 10MB 未満なら、最後のフォルダでなければ次の保存先フォルダを探す
        upload_folder_disk_usage = shutil.disk_usage(upload_folder)
        if upload_folder_disk_usage.free < 10 * 1024 * 1024 and index < len(upload_folders) - 1:
            continue

        # ディレクトリトラバーサル対策のためのチェック
        ## ref: https://stackoverflow.com/a/45190125/17124142
        filename = Path(cast(str, image.filename))
        try:
            upload_folder.joinpath(filename).resolve().relative_to(upload_folder.resolve())
        except ValueError:
            logging.error('[CapturesRouter][CaptureUploadAPI] Invalid filename was specified.')
            raise HTTPException(
                status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail = 'Specified filename is invalid',
            )

        # 保存するファイルパス
        filepath = upload_folder / filename

        # 既にファイルが存在していた場合は上書きしないようにリネーム
        ## ref: https://note.nkmk.me/python-pathlib-name-suffix-parent/
        count = 1
        while filepath.exists():
            filepath = upload_folder / f'{filename.stem}-{count}{filename.suffix}'
            count += 1

        # キャプチャを保存
        try:
            with open(filepath, mode='wb') as buffer:
                shutil.copyfileobj(image.file, buffer)
        except PermissionError:
            logging.error('[CapturesRouter][CaptureUploadAPI] Permission denied to save the file.')
            raise HTTPException(
                status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail = 'Permission denied to save the file',
            )
        except OSError as ex:
            is_disk_full_error = False
            if hasattr(ex, 'winerror'):
                is_disk_full_error = ex.winerror == 112  # type: ignore
            if hasattr(ex, 'errno'):
                is_disk_full_error = ex.errno == errno.ENOSPC
            if is_disk_full_error is True:
                logging.error('[CapturesRouter][CaptureUploadAPI] No space left on the device.')
                raise HTTPException(
                    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail = 'No space left on the device',
                )
            else:
                logging.error('[CapturesRouter][CaptureUploadAPI] Unexpected OSError:', exc_info=ex)
                raise HTTPException(
                    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail = 'Unexpected error occurred while saving the file',
                )

        # キャプチャのアップロードに成功したら 204 No Content を返す
        return

    # 保存先フォルダが見つからなかった場合はエラー
    logging.error('[CapturesRouter][CaptureUploadAPI] No available folder to save the file.')
    raise HTTPException(
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail = 'No available folder to save the file',
    )
