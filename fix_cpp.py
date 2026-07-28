path = "src/main.cpp"
with open(path, 'r') as f:
    content = f.read()

content = content.replace("memcpy(uuid_bytes, bleUUID.getNative()->uuid.uuid128, 16);", "memcpy(uuid_bytes, bleUUID.getNative()->u128.value, 16);")
content = content.replace("oAdvertisementData.addData(strServiceData);", "oAdvertisementData.addData(strServiceData.c_str(), strServiceData.length());")

with open(path, 'w') as f:
    f.write(content)
