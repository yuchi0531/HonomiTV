from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from app import schemas
from app.metadata.SeriesIndexer import IsStrictSeriesTitlePrefix, NormalizeSeriesTitle
from app.models.RecordedProgram import RecordedProgram


class SeriesMatcher:
    """
    外部の作品データベース (Bangumi / Annict) とローカル Series を照合する共通ロジック。

    作品名の表記揺れを吸収した比較と、録画 1 件から視聴完了した話を選ぶ判定だけを持ち、
    外部 API の呼び出しや DB 更新は行わない。各クライアントはここで得た結果を自分の形式へ変換する。
    """

    # 放送版の品質差だけを比較キーから取り除き、作品の期・劇場版などの識別情報は保持する。
    REMASTER_SUFFIX_PATTERN = re.compile(r'\s*(?:(?:[248]K|HD|デジタル)\s*)?リマスター版?\s*$', re.IGNORECASE)
    # 作品名の後ろに付く「期」「劇場版」などの別作品表記
    ## これらが付く候補を前方一致だけで同一作品と扱うと、続編を主条目へ誤って統合してしまう
    SEQUEL_PREFIX_PATTERN = re.compile(
        r'^(?:第\s*[0-9一二三四五六七八九十]+\s*(?:期|部|章|シーズン|クール)|'
        r'[0-9]+|(?:season|part)\s*[0-9]+|'
        r'[ivx]+\b|続編|続・|劇場版|映画|the\s*movie\b|final\s*season\b|ova\b|oad\b)',
        re.IGNORECASE,
    )


    @staticmethod
    def parseEpisodeNumber(episode_number: str | None) -> int | None:
        """
        自動同期で安全に扱える単一の正整数話数だけを取得する。

        Args:
            episode_number (str | None): EPG から抽出した話数。

        Returns:
            int | None: 単一の正整数であればその値、それ以外は None。
        """

        if episode_number is None or episode_number.isdecimal() is False:
            return None
        parsed_number = int(episode_number)
        return parsed_number if parsed_number > 0 else None


    @staticmethod
    def normalizeTitle(title: str) -> str:
        """
        ローカル Series と外部作品のタイトル比較キーを生成する。

        Args:
            title (str): ローカル Series または外部作品のタイトル。

        Returns:
            str: Unicode・空白・末尾句読点・リマスター表記の差を吸収した比較キー。
        """

        # EPG と外部 DB では長い作品名の末尾句点だけが欠けることがあるため、その差だけを追加で吸収する。
        normalized_title = unicodedata.normalize('NFKC', title)
        normalized_title = SeriesMatcher.REMASTER_SUFFIX_PATTERN.sub('', normalized_title)
        return NormalizeSeriesTitle(normalized_title).rstrip('。.!！?？')


    @classmethod
    def isTitlePrefix(cls, short_title: str, long_title: str) -> bool:
        """
        照合に限り、記号または空白で副題を区切る短縮名を比較する。

        Args:
            short_title (str): 副題を省略した作品名。
            long_title (str): 副題を含む作品名。

        Returns:
            bool: 続編ではない明示的な副題境界が確認できた場合に True。
        """

        short_key = cls.normalizeTitle(short_title)
        long_key = cls.normalizeTitle(long_title)
        if not short_key:
            return False
        if IsStrictSeriesTitlePrefix(short_key, long_key):
            return True

        # 空白を消す前に日本語主題の終わりを確認し、英語作品名の単語間空白を副題と誤認しない。
        ## 短すぎる汎用名と、数字・期・劇場版を後置した別作品は弱い候補にも含めない。
        title_parts = unicodedata.normalize('NFKC', long_title).strip().split(maxsplit=1)
        return (
            len(title_parts) == 2 and len(short_key) >= 4 and
            re.search(r'[ぁ-んァ-ヶ一-龯]', short_key) is not None and
            cls.normalizeTitle(title_parts[0]) == short_key and
            cls.SEQUEL_PREFIX_PATTERN.match(title_parts[1]) is None
        )


    @classmethod
    def scoreTitle(cls, series_title: str, candidate_titles: list[str]) -> int:
        """
        ローカル Series の表題と外部作品のタイトル候補を採点する。

        Args:
            series_title (str): ローカル Series の表示タイトル。
            candidate_titles (list[str]): 外部作品が持つタイトル (原題・別表記など)。

        Returns:
            int: タイトル一致度。候補外の場合は 0。
        """

        local_title = cls.normalizeTitle(series_title)
        original_titles = [title for title in candidate_titles if title]
        candidate_keys = {cls.normalizeTitle(title) for title in original_titles} - {''}
        if not local_title or len(candidate_keys) == 0:
            return 0
        if local_title in candidate_keys:
            return 100

        # 長い作品名は期や劇場版の追加後も類似率が高いため、明示的な別作品表記を fuzzy 判定より先に拒否する。
        for candidate_title in candidate_keys:
            short_key, long_key = sorted((local_title, candidate_title), key=len)
            if long_key.startswith(short_key):
                edition_suffix = long_key[len(short_key):].lstrip('~～-―—:：「『【')
                if cls.SEQUEL_PREFIX_PATTERN.match(edition_suffix) is not None:
                    return 0

        # 放送局が副題を省略した表記は、安全な副題境界を持つ場合だけ弱い候補として認める。
        if any(
            cls.isTitlePrefix(series_title, candidate_title) or
            cls.isTitlePrefix(candidate_title, series_title)
            for candidate_title in original_titles
        ):
            return 80

        # 候補一覧に絞った後も僅かな記号・転写差が残るため、長いタイトル同士だけ保守的に類似判定する。
        similarity = max(
            (SequenceMatcher(None, local_title, candidate_title).ratio() for candidate_title in candidate_keys),
            default = 0.0,
        )
        if min([len(local_title), *(len(candidate_title) for candidate_title in candidate_keys)]) >= 8 and similarity >= 0.9:
            return int(similarity * 75)
        return 0


    @classmethod
    def findBestCandidate(
        cls,
        series_title: str,
        candidates: list[tuple[int, str, list[str]]],
    ) -> int | None:
        """
        ローカル Series に対応する外部作品を一意に選ぶ。

        Args:
            series_title (str): ローカル Series の表示タイトル。
            candidates (list[tuple[int, str, list[str]]]): (作品 ID, 代表タイトル, タイトル候補一覧)。

        Returns:
            int | None: 十分に一意な最高得点候補の作品 ID。決められない場合は None。
        """

        scored = sorted(
            ((cls.scoreTitle(series_title, titles), candidate_id) for candidate_id, _, titles in candidates),
            key = lambda candidate: candidate[0],
            reverse = True,
        )
        if len(scored) == 0 or scored[0][0] < 67:
            return None
        # 同点に近い候補が複数ある場合は、誤って別作品へ紐付けないよう自動確定しない
        if len(scored) >= 2 and scored[0][0] - scored[1][0] < 10:
            return None
        return scored[0][1]


    @staticmethod
    def isPlaybackCompleted(
        playback_position: float,
        duration: float,
        cm_sections: list[schemas.CMSection] | None,
    ) -> bool:
        """
        プレイヤーが報告した実再生時間から視聴完了を判定する。

        Args:
            playback_position (float): 現在の再生位置 (秒)。
            duration (float): サーバーに保存されている録画時間 (秒)。
            cm_sections (list[schemas.CMSection] | None): サーバーで検出済みの CM 区間。

        Returns:
            bool: CM 区間を考慮した視聴完了位置まで再生済みなら True。
        """

        return playback_position >= schemas.GetPlaybackCompletionThreshold(duration, cm_sections)


    @classmethod
    def selectPlaybackEpisode(
        cls, recorded_program: RecordedProgram, playback_position: float, duration: float,
    ) -> tuple[int | None, bool, bool]:
        """
        録画・放送局・現在位置から、今回だけ更新できる話数と完了判定を選ぶ。

        Args:
            recorded_program (RecordedProgram): 話数と放送局を読み込み済みの録画。
            playback_position (float): ファイル先頭基準の現在位置 (秒)。
            duration (float): プレイヤーが解決したファイル時間 (秒)。

        Returns:
            tuple[int | None, bool, bool]: 対象話数、範囲録画かどうか、完了位置到達かどうか。
        """

        episode_number = cls.parseEpisodeNumber(recorded_program.episode_number)
        channel = recorded_program.channel
        is_atx_anime = (
            channel is not None and channel.type == 'CS' and channel.service_id == 333
            and any('アニメ' in genre['major'] and '特撮' not in genre['middle'] for genre in recorded_program.genres)
            and recorded_program.is_partially_recorded is False
        )
        # 単話は従来の CM/90% 判定を基本とし、CS333 の通常アニメ枠だけ 20 分へ置き換える。
        if episode_number is not None:
            if is_atx_anime and 27 * 60 <= recorded_program.duration <= 36 * 60:
                return episode_number, False, playback_position >= 20 * 60
            completion_duration = recorded_program.recorded_video.duration \
                if recorded_program.recorded_video.cm_sections else duration
            return episode_number, False, cls.isPlaybackCompleted(
                playback_position, completion_duration, recorded_program.recorded_video.cm_sections,
            )

        # UI が認識済みの連続範囲だけを使う。タイトルから新たな範囲や話数を推測しない。
        match = re.fullmatch(r'([0-9]+)-([0-9]+)', recorded_program.episode_number or '')
        if not is_atx_anime or match is None:
            return None, False, False
        first_episode, last_episode = (int(value) for value in match.groups())
        episode_count = last_episode - first_episode + 1
        if first_episode <= 0 or episode_count <= 1:
            return None, True, False
        # 半時間枠の連続放送だけを対象とし、映画・短編・欠損録画へ機械的な 30 分分割を適用しない。
        slot_duration = recorded_program.duration / episode_count
        if not 27 * 60 <= slot_duration <= 36 * 60:
            return None, True, False
        slot_index = int(playback_position // (30 * 60))
        # 最終話後の録画マージンでは最終話を維持するが、余分な話数は生成しない。
        slot_index = min(slot_index, episode_count - 1)
        threshold = slot_index * 30 * 60 + 20 * 60
        return first_episode + slot_index, True, playback_position >= threshold


def GetCandidateTitles(candidate: dict[str, Any], title_keys: tuple[str, ...]) -> list[str]:
    """
    外部作品の辞書から、照合に使うタイトル候補を取り出す。

    Args:
        candidate (dict[str, Any]): 外部 API が返した作品の辞書。
        title_keys (tuple[str, ...]): タイトルが入っているキー名 (原題・別表記など)。

    Returns:
        list[str]: 空でないタイトルのリスト。
    """

    return [str(candidate.get(key, '')) for key in title_keys if candidate.get(key)]
