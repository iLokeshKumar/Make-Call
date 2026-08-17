import kagglehub

handle = "lokeshk431/multilingual-voice-recordings"
local_dataset_dir = r"E:\something_new\audio\my_voice_recordings_upload.zip"

kagglehub.dataset_upload(
    handle,
    local_dataset_dir,
    version_notes="Initial upload: 3 speakers, multilingual raw normalized voice recordings"
)