import math

ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def base62_encode(number):
    """将数字转换为 base62 编码。"""
    if number == 0:
        return '0'

    result = ''
    while number > 0:
        result = ALPHABET[number % 62] + result
        number //= 62

    return result


def mid2id(mid):
    mid = str(mid)[::-1]
    size = math.ceil(len(mid) / 7)
    result = []

    for i in range(size):
        s = mid[i * 7:(i + 1) * 7][::-1]
        s = base62_encode(int(s))
        if i < size - 1 and len(s) < 4:
            s = '0' * (4 - len(s)) + s
        result.append(s)

    result.reverse()
    return ''.join(result)


