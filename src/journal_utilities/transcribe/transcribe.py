"""
This module handles the transcription of audio files using WhisperX,
and updates the transcription status in the database.
"""

import asyncio
import json
import logging
import os
import subprocess

import whisperx
from surrealdb import AsyncSurreal
from whisperx.diarize import DiarizationPipeline

logger = logging.getLogger(__name__)


class TranscriptionService:
    """
    A service for transcribing audio files using WhisperX, including alignment and diarization.

    Attributes:
        hf_token (str): Hugging Face token for authentication.
        device (str): Device to use for computation (e.g., 'cuda').
        batch_size (int): Batch size for transcription.
        compute_type (str): Compute type (e.g., 'float16', 'int8').
    """

    def __init__(self, hf_token, device, batch_size, compute_type):
        self.device = device
        self.batch_size = batch_size
        self.hf_token = hf_token
        self.compute_type = compute_type
        self.model = whisperx.load_model(
            "large-v3", device, compute_type=compute_type, language="en"
        )

        # Load alignment model and diarization pipeline during initialization
        self.align_model, self.metadata = whisperx.load_align_model(
            language_code="en", device=device
        )
        self.diarize_model = DiarizationPipeline(use_auth_token=hf_token, device=device)

    def download_audio(self, video_url, output_wav_file, ffmpeg_location="/usr/bin"):
        """Function to download and prepare the audio file"""
        # A modern browser User-Agent is required to avoid YouTube 403s, and a
        # timeout prevents an unbounded network hang (see AGENTS.md).
        subprocess.run(
            [
                "yt-dlp",
                "-xv",
                "--user-agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "--ffmpeg-location",
                ffmpeg_location,
                "--audio-format",
                "wav",
                "-o",
                output_wav_file,
                "--",
                video_url,
            ],
            check=True,
            timeout=600,
        )

    def remove_words(self, obj):
        """
        Recursively remove 'words' key from dictionaries and lists.

        Args:
            obj (dict or list): The object to process.

        Returns:
            dict or list: The processed object with 'words' key removed.
        """
        if isinstance(obj, dict):
            obj = {k: self.remove_words(v) for k, v in obj.items() if k != "words"}
        elif isinstance(obj, list):
            obj = [self.remove_words(item) for item in obj]
        return obj

    def simplify_transcript(self, detailed_transcript):
        """
        Simplify the transcript by removing 'words' arrays.

        Args:
            detailed_transcript (dict): The detailed transcript.

        Returns:
            dict: The simplified transcript.
        """
        return self.remove_words(detailed_transcript)

    def output_text(self, simple_transcript):
        """
        Convert simplified transcript to a formatted text string.

        Args:
            simple_transcript (list): The simplified transcript.

        Returns:
            str: The formatted text string.
        """
        output = ""
        prev_speaker = None

        for segment in simple_transcript:
            speaker = segment.get("speaker", "UNKNOWN")
            text = segment.get("text", "").strip()

            if text:
                if speaker != prev_speaker:
                    output += f"\n{speaker}:\n"
                    prev_speaker = speaker

                output += text + "\n\n"

        return output.strip()

    def transcribe(self, output_dir, audio_file):
        """
        Transcribe an audio file and save the results in various formats.

        Args:
            output_dir (str): Path to folder to store the json and txt files
            audio_file (str): Path to the audio file.

        Returns:
            None
        """
        try:
            # 1. Transcribe with original whisper (batched)
            logger.info("Loading audio file: %s", audio_file)
            audio = whisperx.load_audio(audio_file)
            logger.info("Starting transcription with WhisperX model")
            result = self.model.transcribe(audio, batch_size=self.batch_size)
            logger.info(
                "Transcription complete, %d segments found", len(result.get("segments", []))
            )

            # 2. Align whisper output
            logger.info("Starting alignment")
            result = whisperx.align(
                result["segments"],
                self.align_model,
                self.metadata,
                audio,
                self.device,
                return_char_alignments=False,
            )
            logger.info("Alignment complete")

            # 3. Assign speaker labels
            logger.info("Starting diarization")
            diarize_segments = self.diarize_model(audio)
            logger.info("Diarization complete, assigning speaker labels")
            result = whisperx.assign_word_speakers(diarize_segments, result)
            logger.info("Speaker assignment complete")

            # 4. Write to JSON file
            result_segments = result["segments"]
            base_filename = os.path.splitext(os.path.basename(audio_file))[0]
            output_file = os.path.join(output_dir, f"{base_filename}.json")
            logger.info("Writing full JSON to %s", output_file)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result_segments, f, indent=2)
            logger.info("Transcription saved to %s", output_file)

            # 5. Write simplified JSON file without the 'words' list
            output_simple_file = os.path.join(output_dir, f"{base_filename}.simple.json")
            logger.info("Writing simplified JSON to %s", output_simple_file)
            result_simple = self.simplify_transcript(result_segments)
            with open(output_simple_file, "w", encoding="utf-8") as f:
                json.dump(result_simple, f, indent=2)

            # 6. Write simplified TXT file
            output_simple_txt_file = os.path.join(output_dir, f"{base_filename}.simple.txt")
            logger.info("Writing simplified TXT to %s", output_simple_txt_file)
            result_simple_txt = self.output_text(result_simple)
            with open(output_simple_txt_file, "w", encoding="utf-8") as f:
                f.write(result_simple_txt)
            logger.info("All output files written successfully")
        except Exception as e:
            logger.error("An error occurred during transcription of %s: %s", audio_file, e)
            raise  # Re-raise the exception to propagate it


async def transcribe_and_update(transcription_service, db, session, wav_directory, output_dir):
    """
    Transcribe an audio file and update the database.

    Args:
        transcription_service (TranscriptionService): The transcription service instance.
        db (AsyncSurreal): The database connection.
        session (dict): The session information.
        wav_directory (str): The directory containing the WAV files.
        output_dir (str): Path to folder to store the json and txt files

    Returns:
        None
    """
    try:
        audio_file = f"{wav_directory}/{session['filename']}"
        session_id = session["id"]
        logger.info("Transcription started for session %s", session_id)
        # WhisperX is CPU/GPU-heavy and blocking; don't stall the event loop.
        await asyncio.to_thread(transcription_service.transcribe, output_dir, audio_file)
        update_result = await db.query(
            "UPDATE $id MERGE { transcribed: true, transcript_method: 'WhisperX' };",
            {"id": session_id},
        )
        logger.info(
            "Transcription and update complete for session  %s: %s", session_id, update_result
        )
    except (OSError, RuntimeError) as e:
        logger.error(
            "An error occurred during transcribe and db update of %s record: %s",
            session["filename"],
            e,
        )


async def process_untranscribed_sessions(
    db_url,
    db_user,
    db_password,
    db_name,
    db_namespace,
    wav_directory,
    output_dir,
    hf_token,
    device,
    batch_size,
    compute_type,
):
    """
    Read in all the sessions in the database that haven't been transcribed and run
    download_and_transcribe for each one (extracting WAV if needed, then transcribing)

    Args:
        db_url (str): Database URL
        db_user (str): Database username
        db_password (str): Database password
        db_name (str): Database name
        db_namespace (str): Database namespace
        wav_directory (str): The directory containing the WAV files to process.
        output_dir (str): Path to folder to store the json and txt files
        hf_token (str): Hugging Face token for authentication.
        device (str): Device to use for computation (e.g., 'cuda').
        batch_size (int): Batch size for transcription.
        compute_type (str): Compute type (e.g., 'float16', 'int8').

    Returns:
        None
    """
    try:
        # Create a single TranscriptionService instance to reuse across all sessions
        transcription_service = TranscriptionService(hf_token, device, batch_size, compute_type)

        async with AsyncSurreal(db_url) as db:
            await db.signin({"username": db_user, "password": db_password})
            await db.use(db_namespace, db_name)

            result = await db.query(
                "SELECT * FROM session WHERE transcribed = FALSE AND is_private != TRUE AND scheduled_date < time::now() - 1d;"
            )
            sessions = result[0] if result else []

            if sessions:
                for session in sessions:
                    session_name = session.get("session_name")
                    if not session_name:
                        logger.warning(
                            "Session %s has no session_name, skipping", session.get("id")
                        )
                        continue

                    await download_and_transcribe(
                        session_name, db, transcription_service, wav_directory, output_dir
                    )
            else:
                logger.info("No unprocessed sessions found.")
    except Exception as e:  # pylint: disable=broad-except
        logger.error("An error occurred during query and transcription: %s", e)


async def download_and_transcribe(
    session_name, db, transcription_service, wav_directory, output_dir
):
    """
    Downloads an audio file to the wav_directory, transcribes the wav file,
    and saves the transcript to the output_dir

    Args:
        session_name: youtube video ID (e.g., 'v4sAeY06ngs')
        db (AsyncSurreal): Database connection
        transcription_service (TranscriptionService): The transcription service instance
        wav_directory (str): The directory containing the WAV files
        output_dir (str): Path to folder to store the json and txt files

    Returns:
        None
    """
    # Construct the output WAV filename
    output_wav_file = os.path.join(wav_directory, f"{session_name}.wav")

    try:
        result = await db.query(
            "SELECT * FROM session WHERE session_name = $name", {"name": session_name}
        )
        rows = result[0] if result else []
        if not rows:
            logger.error("Session with session_name %s not found in database", session_name)
            return

        session = rows[0]

        # Construct video URL from session_name
        video_url = f"https://www.youtube.com/watch?v={session_name}"

        if not session.get("wav_extracted"):
            transcription_service.download_audio(video_url, output_wav_file)
            logger.info("Successfully downloaded audio for session: %s", session_name)

            # Update the existing session in the database
            update_result = await db.query(
                "UPDATE $id MERGE { filename: $filename, wav_extracted: true }",
                {"id": session["id"], "filename": f"{session_name}.wav"},
            )
            logger.info("Updated session in database: %s", update_result)
            session["filename"] = f"{session_name}.wav"
            session["wav_extracted"] = True
        else:
            logger.info("Session %s already downloaded", session_name)

        # Transcribe the audio and update the database if not already transcribed
        if not session.get("transcribed"):
            await transcribe_and_update(
                transcription_service, db, session, wav_directory, output_dir
            )
        else:
            logger.info("Session %s already transcribed", session_name)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to download audio for session %s: %s", session_name, str(e))
        return
    except Exception as e:
        logger.error("Failed to process session %s: %s", session_name, str(e))
        return


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()  # loads .env from the current working directory
    HF_TOKEN = os.getenv("HF_TOKEN")
    DEVICE = "cuda"
    BATCH_SIZE = 48  # reduce if low on GPU mem
    COMPUTE_TYPE = "float16"  # change to "int8" if low on GPU mem (may reduce accuracy)
    WAV_DIRECTORY = os.getenv("WAV_DIRECTORY")
    OUTPUT_DIR = os.getenv("OUTPUT_DIR")
    DB_URL = os.getenv("DB_URL")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_NAME = os.getenv("DB_NAME")
    DB_NAMESPACE = os.getenv("DB_NAMESPACE")

    asyncio.run(
        process_untranscribed_sessions(
            DB_URL,
            DB_USER,
            DB_PASSWORD,
            DB_NAME,
            DB_NAMESPACE,
            WAV_DIRECTORY,
            OUTPUT_DIR,
            HF_TOKEN,
            DEVICE,
            BATCH_SIZE,
            COMPUTE_TYPE,
        )
    )
