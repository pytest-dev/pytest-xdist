import pytest
import time


@pytest.mark.xdist_custom(name="low_4")
def test_1():
    time.sleep(2)
    assert True

@pytest.mark.xdist_custom(name="low_4")
def test_2():
    time.sleep(2)
    assert True

@pytest.mark.xdist_custom(name="low_4")
def test_3():
    time.sleep(2)
    assert True

@pytest.mark.xdist_custom(name="low_4")
def test_4():
    time.sleep(2)
    assert True

# @pytest.mark.xdist_custom(name="low_4")
# def test_4a():
#     time.sleep(2)
#     assert True
#
# @pytest.mark.xdist_custom(name="low_4")
# def test_4b():
#     time.sleep(2)
#     assert True
#
# @pytest.mark.xdist_custom(name="low_4")
# def test_4c():
#     time.sleep(2)
#     assert True
#
# @pytest.mark.xdist_custom(name="low_4")
# def test_4d():
#     time.sleep(2)
#     assert True
#
# @pytest.mark.xdist_custom(name="low_4")
# def test_4e():
#     time.sleep(2)
#     assert True

@pytest.mark.xdist_custom(name="med_2")
def test_5():
    time.sleep(3)
    assert True

@pytest.mark.xdist_custom(name="med_2")
def test_6():
    time.sleep(3)
    assert True

@pytest.mark.xdist_custom(name="med_2")
def test_7():
    time.sleep(3)
    assert True

@pytest.mark.xdist_custom(name="med_2")
def test_8():
    time.sleep(3)
    assert True

@pytest.mark.xdist_custom(name="high_1")
def test_9():
    time.sleep(5)
    assert True

@pytest.mark.xdist_custom(name="high_1")
def test_10():
    time.sleep(5)
    assert True

def test_11():
    time.sleep(1)
    assert True

def test_12():
    time.sleep(1)
    assert True

def test_13():
    time.sleep(1)
    assert True

def test_14():
    time.sleep(1)
    assert True
