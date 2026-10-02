// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title Figurae (FIG)
/// @notice An AI-inspired meme token with a fixed supply and a 30% initial founders allocation.
/// @dev Founders allocations describe issuance only; tokens can subsequently be transferred.
contract Figurae is ERC20 {
    uint256 public constant MAX_SUPPLY = 100_000_000_000 * 10 ** 18;
    uint256 public constant FOUNDERS_ALLOCATION = MAX_SUPPLY * 30 / 100;
    uint256 public constant DISTRIBUTION_ALLOCATION = MAX_SUPPLY - FOUNDERS_ALLOCATION;
    uint256 public constant FOUNDERS_BPS = 3_000;
    uint256 public constant BPS_DENOMINATOR = 10_000;
    uint256 public constant MAX_FOUNDERS = 50;
    string public constant THEME = "AI-inspired meme token";

    /// @notice The initial distribution wallet, which receives 70% of the fixed supply.
    address public immutable distributionWallet;

    /// @notice The number of smallest token units originally issued to each founder.
    /// @dev This value is not updated when a founder sends or receives tokens.
    mapping(address => uint256) public founderAllocation;

    error InvalidFounderCount(uint256 count);
    error FounderArrayLengthMismatch(uint256 foundersLength, uint256 allocationsLength);
    error InvalidDistributionWallet();
    error InvalidFounder(uint256 index);
    error DuplicateFounder(address founder);
    error FounderIsDistributionWallet(address founder);
    error InvalidFounderShare(uint256 index);
    error InvalidFoundersShareTotal(uint256 total);

    /// @param founders Distinct wallets that will receive the founders allocation.
    /// @param founderBps Each founder's share of total supply in basis points, summing to 3,000.
    /// @param distributionWallet_ A different wallet for the remaining 70%.
    constructor(
        address[] memory founders,
        uint16[] memory founderBps,
        address distributionWallet_
    ) ERC20("Figurae", "FIG") {
        uint256 count = founders.length;
        if (count == 0 || count > MAX_FOUNDERS) revert InvalidFounderCount(count);
        if (count != founderBps.length) {
            revert FounderArrayLengthMismatch(count, founderBps.length);
        }
        if (distributionWallet_ == address(0)) revert InvalidDistributionWallet();

        uint256 totalBps;
        for (uint256 i; i < count; ++i) {
            address founder = founders[i];
            if (founder == address(0)) revert InvalidFounder(i);
            if (founder == distributionWallet_) revert FounderIsDistributionWallet(founder);
            if (founderBps[i] == 0) revert InvalidFounderShare(i);
            for (uint256 j; j < i; ++j) {
                if (founders[j] == founder) revert DuplicateFounder(founder);
            }
            totalBps += founderBps[i];
        }
        if (totalBps != FOUNDERS_BPS) revert InvalidFoundersShareTotal(totalBps);

        distributionWallet = distributionWallet_;
        for (uint256 i; i < count; ++i) {
            // MAX_SUPPLY is divisible by BPS_DENOMINATOR: every share is exact.
            uint256 allocation = MAX_SUPPLY * founderBps[i] / BPS_DENOMINATOR;
            founderAllocation[founders[i]] = allocation;
            _mint(founders[i], allocation);
        }
        _mint(distributionWallet_, DISTRIBUTION_ALLOCATION);
    }
}
